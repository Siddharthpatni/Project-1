"""
Celery task definitions.

Kept thin: each task opens a DB session, resolves resources, and
delegates to the appropriate phase module. Business logic stays in
`phase1_*`, `phase2_*`, `phase3_*`.
"""
from __future__ import annotations

import asyncio
import time

from app.core.llm_client import LLMClient
from app.core.storage import ObjectStorage
from app.database import SessionLocal
from app.models import AgentRun, EvaluationRun, Job, JobStatus, Strategy
from app.phase1_llm_scraper.evaluator import load_dataset
from app.phase1_llm_scraper.feedback_loop import run_feedback_loop
from app.phase2_cua.orchestrator import run_agent
from app.phase3_integration.pipeline import process_url
from app.utils.logger import get_logger
from app.workers.celery_app import celery_app

log = get_logger(__name__)


# --------------------------------------------------------------------
# Main job processing — Phase 3 cascade for every URL in a job.
# --------------------------------------------------------------------

@celery_app.task(name="app.workers.tasks.process_job_task", bind=True)
def process_job_task(
    self,
    job_id: str,
    force_strategy: str | None = None,
    force_model: str | None = None,
) -> dict:
    db = SessionLocal()

    job: Job | None = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        db.close()
        return {"error": "job not found", "job_id": job_id}

    job.status = JobStatus.RUNNING.value
    db.commit()

    force = None
    if force_strategy:
        try:
            force = Strategy(force_strategy)
        except ValueError:
            log.warning("job.invalid_force_strategy", value=force_strategy)

    try:
        # LLMClient and ObjectStorage are created inside the async scope
        # by _process_job_async to keep the httpx client bound to the loop.
        asyncio.run(_process_job_async(db, job, force_model, force))
    except Exception as e:  # noqa: BLE001
        log.exception("job.failed", job_id=job_id)
        job.status = JobStatus.FAILED.value
        db.commit()
        db.close()
        return {"error": str(e), "job_id": job_id}

    # Re-fetch counts after all items processed
    db.refresh(job)
    n_success = sum(1 for i in job.items if i.status == JobStatus.SUCCESS.value)
    total_urls = job.total_urls  # capture before commit expires the object
    if n_success == total_urls:
        job.status = JobStatus.SUCCESS.value
    elif n_success == 0:
        job.status = JobStatus.FAILED.value
    else:
        job.status = JobStatus.PARTIAL.value
    job.completed = n_success
    db.commit()
    db.close()
    return {"job_id": job_id, "success": n_success, "total": total_urls}


async def _process_job_async(db, job, force_model: str | None, force_strategy):
    llm = LLMClient(default_model=force_model)
    storage = ObjectStorage()
    for item in job.items:
        try:
            result = await process_url(db, item, llm, storage, force_strategy)
        except Exception as e:  # noqa: BLE001
            log.exception("job.item_failed", item_id=item.id)
            item.status = JobStatus.FAILED.value
            item.error_message = str(e)[:1000]
            db.commit()
            continue
        job.cost_usd = (job.cost_usd or 0.0) + (result.cost_usd or 0.0)
        job.completed = sum(
            1 for i in job.items if i.status == JobStatus.SUCCESS.value
        )
        db.commit()


# --------------------------------------------------------------------
# Phase 1 evaluation harness
# --------------------------------------------------------------------

@celery_app.task(name="app.workers.tasks.run_evaluation_task")
def run_evaluation_task(dataset_path: str, models: list[str], max_iterations: int = 5) -> dict:
    try:
        dataset = load_dataset(dataset_path)
    except FileNotFoundError as e:
        return {"error": str(e)}

    # One asyncio.run() for the whole evaluation so the httpx.AsyncClient
    # inside LLMClient stays alive across all URL iterations.
    return asyncio.run(_run_evaluation_async(dataset, models, max_iterations))


async def _run_evaluation_async(dataset, models: list[str], max_iterations: int) -> dict:
    db = SessionLocal()
    # LLMClient created inside the event loop so its httpx.AsyncClient is
    # bound to the correct loop for the full duration of the eval run.
    llm = LLMClient()
    results = []

    for model in models:
        for truth in dataset:
            t0 = time.time()
            try:
                loop_result = await run_feedback_loop(
                    url=truth.url,
                    llm=llm,
                    ground_truth=truth,
                    model=model,
                    max_iterations=max_iterations,
                )
                run = EvaluationRun(
                    model=model,
                    url=truth.url,
                    expected_docs=truth.expected_doc_count,
                    downloaded_docs=loop_result.metrics.downloaded_count if loop_result.metrics else 0,
                    success=loop_result.success,
                    iterations=loop_result.iterations,
                    runtime_seconds=time.time() - t0,
                    cost_usd=loop_result.total_cost_usd,
                    notes=(loop_result.final_execution.error if loop_result.final_execution else None) or "",
                )
            except Exception as e:  # noqa: BLE001
                log.exception("evaluation.run_failed", model=model, url=truth.url)
                run = EvaluationRun(
                    model=model,
                    url=truth.url,
                    expected_docs=truth.expected_doc_count,
                    downloaded_docs=0,
                    success=False,
                    iterations=0,
                    runtime_seconds=time.time() - t0,
                    cost_usd=0.0,
                    notes=str(e)[:1000],
                )
            db.add(run)
            db.commit()
            results.append({"model": model, "url": truth.url, "success": run.success})

    db.close()
    return {"runs": len(results), "results": results}


# --------------------------------------------------------------------
# Phase 2 CUA run
# --------------------------------------------------------------------

@celery_app.task(name="app.workers.tasks.run_cua_task")
def run_cua_task(agent_name: str, url: str, max_steps: int | None = None, model_name: str | None = None) -> dict:
    db = SessionLocal()
    llm = LLMClient()

    t0 = time.time()
    try:
        outcome = asyncio.run(
            run_agent(agent_name=agent_name, url=url, llm=llm, max_steps=max_steps or 30, model_name=model_name)
        )
    except Exception as e:  # noqa: BLE001
        log.exception("cua.task.failed")
        db.close()
        return {"error": str(e)}

    row = AgentRun(
        agent_name=agent_name,
        url=url,
        steps=outcome.steps,
        success=outcome.success,
        runtime_seconds=time.time() - t0,
        cost_usd=outcome.cost_usd,
        trace={"steps": outcome.trace[:50]},  # cap to keep payload small
    )
    db.add(row)
    db.commit()
    db.close()
    return {
        "agent": agent_name,
        "success": outcome.success,
        "downloaded": len(outcome.downloaded_files),
        "steps": outcome.steps,
    }


# --------------------------------------------------------------------
# Periodic document versioning check (beat schedule)
# --------------------------------------------------------------------

@celery_app.task(name="app.workers.tasks.check_document_versions_task")
def check_document_versions_task() -> dict:
    """Re-run known scrapers and bump document versions if content changed.

    For every domain in the registry that's not retired, fetch the
    current snapshot, compare to last known checksums, and bump
    `document.version` for changed files. The full implementation
    lives behind a separate per-domain task to keep beat ticks cheap.
    """
    from app.models import ScraperTemplate
    from app.phase3_integration.scraper_registry import should_retire

    db = SessionLocal()
    log.info("versioning.tick")
    try:
        templates = db.query(ScraperTemplate).all()
        domains_checked = 0
        for tpl in templates:
            if should_retire(tpl):
                continue
            domains_checked += 1
            # Per-domain re-checks are intentionally NOT performed inline
            # — they would block beat. A future per-domain task would
            # enqueue here. For now we just count.
        return {"checked": domains_checked, "updated": 0}
    finally:
        db.close()
