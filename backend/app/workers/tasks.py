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
from app.models import AgentRun, EvaluationRun, Job, JobItem, JobStatus, Strategy
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

@celery_app.task(name="app.workers.tasks.process_job_task")
def process_job_task(job_id: str, force_strategy: str | None = None) -> dict:
    db = SessionLocal()
    llm = LLMClient()
    storage = ObjectStorage()

    job: Job | None = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        db.close()
        return {"error": "job not found", "job_id": job_id}

    job.status = JobStatus.RUNNING
    db.commit()

    force = Strategy(force_strategy) if force_strategy else None

    try:
        asyncio.run(_process_job_async(db, job, llm, storage, force))
    except Exception as e:  # noqa: BLE001
        log.exception("job.failed", job_id=job_id)
        job.status = JobStatus.FAILED
        db.commit()
        db.close()
        return {"error": str(e), "job_id": job_id}

    # Final status
    n_success = sum(1 for i in job.items if i.status == JobStatus.SUCCESS)
    if n_success == job.total_urls:
        job.status = JobStatus.SUCCESS
    elif n_success == 0:
        job.status = JobStatus.FAILED
    else:
        job.status = JobStatus.PARTIAL
    job.completed = n_success
    db.commit()
    db.close()
    return {"job_id": job_id, "success": n_success, "total": job.total_urls}


async def _process_job_async(db, job, llm, storage, force_strategy):
    for item in job.items:
        result = await process_url(db, item, llm, storage, force_strategy)
        job.cost_usd = (job.cost_usd or 0.0) + result.cost_usd
        db.commit()


# --------------------------------------------------------------------
# Phase 1 evaluation harness
# --------------------------------------------------------------------

@celery_app.task(name="app.workers.tasks.run_evaluation_task")
def run_evaluation_task(dataset_path: str, models: list[str], max_iterations: int = 5) -> dict:
    db = SessionLocal()
    llm = LLMClient()

    try:
        dataset = load_dataset(dataset_path)
    except FileNotFoundError as e:
        db.close()
        return {"error": str(e)}

    results = []
    for model in models:
        for truth in dataset:
            t0 = time.time()
            try:
                loop = asyncio.run(
                    run_feedback_loop(
                        url=truth.url,
                        llm=llm,
                        ground_truth=truth,
                        model=model,
                        max_iterations=max_iterations,
                    )
                )
                run = EvaluationRun(
                    model=model,
                    url=truth.url,
                    expected_docs=truth.expected_doc_count,
                    downloaded_docs=loop.metrics.downloaded_count if loop.metrics else 0,
                    success=loop.success,
                    iterations=loop.iterations,
                    runtime_seconds=time.time() - t0,
                    cost_usd=loop.total_cost_usd,
                    notes=(loop.final_execution.error if loop.final_execution else None) or "",
                )
            except Exception as e:  # noqa: BLE001
                run = EvaluationRun(
                    model=model,
                    url=truth.url,
                    expected_docs=truth.expected_doc_count,
                    downloaded_docs=0,
                    success=False,
                    iterations=0,
                    runtime_seconds=time.time() - t0,
                    cost_usd=0.0,
                    notes=str(e),
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
def run_cua_task(agent_name: str, url: str, max_steps: int | None = None) -> dict:
    db = SessionLocal()
    llm = LLMClient()

    t0 = time.time()
    try:
        outcome = asyncio.run(run_agent(agent_name=agent_name, url=url, llm=llm, max_steps=max_steps or 30))
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
    """Re-run known scrapers and bump document versions if content changed."""
    # Intentionally a stub — expand during phase 3 implementation week.
    log.info("versioning.tick")
    return {"checked": 0, "updated": 0}
