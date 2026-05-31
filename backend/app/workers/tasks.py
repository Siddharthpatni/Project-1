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

@celery_app.task(name="app.workers.tasks.process_job_task", bind=True)
def process_job_task(
    self,
    job_id: str,
    force_strategy: str | None = None,
    force_model: str | None = None,
) -> dict:
    """
    Orchestrate a scraping job.

    For small jobs (<= JOB_CHUNK_SIZE URLs): process directly with
    parallel asyncio within this worker.

    For large jobs (> JOB_CHUNK_SIZE): fan out into per-chunk Celery
    sub-tasks so multiple workers share the load, then finalize.
    """
    from app.config import settings as cfg

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

    item_ids = [item.id for item in job.items]
    total_urls = job.total_urls

    if total_urls <= cfg.job_chunk_size:
        # ── Small job: process everything locally ──────────────────────
        try:
            asyncio.run(_process_job_async(db, job, force_model, force))
        except Exception as e:  # noqa: BLE001
            log.exception("job.failed", job_id=job_id)
            job.status = JobStatus.FAILED.value
            db.commit()
            db.close()
            return {"error": str(e), "job_id": job_id}
    else:
        # ── Large job: fan out in chunks ────────────────────────────────
        db.close()
        db = None
        chunks = [
            item_ids[i : i + cfg.job_chunk_size]
            for i in range(0, len(item_ids), cfg.job_chunk_size)
        ]
        log.info(
            "job.fanout", job_id=job_id,
            total_urls=total_urls, chunks=len(chunks),
            chunk_size=cfg.job_chunk_size,
        )
        # Dispatch chunk tasks and wait for all to complete
        from celery import group as celery_group
        chunk_tasks = celery_group(
            process_chunk_task.s(job_id, chunk, force_strategy, force_model)
            for chunk in chunks
        )
        result = chunk_tasks.apply_async()
        # Block this orchestrator task until all chunks finish
        result.get(timeout=cfg.sandbox_timeout_seconds * total_urls, propagate=False)
        db = SessionLocal()

    if db is None:
        db = SessionLocal()
    db.expire_all()
    job = db.query(Job).filter(Job.id == job_id).first()
    n_success = sum(1 for i in job.items if i.status == JobStatus.SUCCESS.value)
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


@celery_app.task(name="app.workers.tasks.process_chunk_task", bind=True, queue="chunks")
def process_chunk_task(
    self,
    job_id: str,
    item_ids: list[str],
    force_strategy: str | None = None,
    force_model: str | None = None,
) -> dict:
    """
    Process a chunk of URL items in parallel within a single worker.

    Multiple workers can each be handling a different chunk simultaneously,
    giving horizontal scale-out for large jobs.
    """
    db = SessionLocal()
    job: Job | None = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        db.close()
        return {"error": "job not found"}

    items = [i for i in job.items if i.id in set(item_ids)]
    force = None
    if force_strategy:
        try:
            force = Strategy(force_strategy)
        except ValueError:
            pass

    try:
        asyncio.run(_process_items_async(db, job, items, force_model, force))
    except Exception as e:  # noqa: BLE001
        log.exception("chunk.failed", job_id=job_id, chunk_size=len(items))
    finally:
        db.close()

    return {"job_id": job_id, "chunk_size": len(item_ids)}


async def _process_job_async(db, job, force_model: str | None, force_strategy):
    """Process all items in a job with bounded concurrency."""
    await _process_items_async(db, job, job.items, force_model, force_strategy)


async def _process_items_async(db, job, items, force_model: str | None, force_strategy):
    """
    Process a list of items with a per-worker concurrency semaphore.

    CRITICAL: Each concurrent coroutine gets its OWN SQLAlchemy session.
    SQLAlchemy sessions are NOT safe for concurrent use — sharing one across
    asyncio.gather() coroutines causes silent data corruption, deadlocks, and
    'object already attached to a different session' errors at scale.

    The parent `db` session is used ONLY for atomic progress/cost updates
    which are protected by a per-function asyncio lock.
    """
    from app.config import settings as cfg

    llm      = LLMClient(default_model=force_model)
    storage  = ObjectStorage()
    sem      = asyncio.Semaphore(cfg.job_concurrency)
    db_lock  = asyncio.Lock()   # serialise writes back to the parent session

    job_id = job.id  # capture before any possible session expiry

    async def _process_one(item_id: str):
        async with sem:
            # Each coroutine opens and closes its own DB session independently.
            item_db = SessionLocal()
            try:
                # Re-fetch item in the coroutine's own session
                item = item_db.query(JobItem).filter(JobItem.id == item_id).first()
                if item is None:
                    return 0.0

                result = await process_url(item_db, item, llm, storage, force_strategy)
                return result.cost_usd or 0.0
            except Exception as e:  # noqa: BLE001
                log.exception("job.item_failed", item_id=item_id)
                try:
                    item = item_db.query(JobItem).filter(JobItem.id == item_id).first()
                    if item:
                        item.status = JobStatus.FAILED.value
                        item.error_message = str(e)[:1000]
                        item_db.commit()
                except Exception:
                    item_db.rollback()
                return 0.0
            finally:
                item_db.close()

    # Fan out all items concurrently
    costs = await asyncio.gather(*(_process_one(item.id) for item in items))

    # Atomic progress update in the parent session (serialised)
    async with db_lock:
        try:
            db.expire_all()
            job_obj = db.query(Job).filter(Job.id == job_id).first()
            if job_obj:
                job_obj.cost_usd = (job_obj.cost_usd or 0.0) + sum(c for c in costs if c)
                job_obj.completed = (
                    db.query(JobItem)
                    .filter(JobItem.job_id == job_id, JobItem.status == JobStatus.SUCCESS.value)
                    .count()
                )
                db.commit()
        except Exception:
            db.rollback()


# --------------------------------------------------------------------
# Smart domain-aware batch — 1 URL/domain, auto-fallback on failure
# --------------------------------------------------------------------

@celery_app.task(name="app.workers.tasks.smart_domain_batch_task", bind=True)
def smart_domain_batch_task(
    self,
    primary_job_id: str,
    backup_map: dict[str, str],        # domain → backup_url
    submitted_by: str | None = None,
    force_strategy: str | None = None,
    force_model: str | None = None,
) -> dict:
    """
    1. Run the primary job (one URL per domain) using the normal cascade.
    2. After it finishes, identify domains whose URL failed.
    3. If a backup URL exists for that domain, create a NEW job and
       run it — so the scraper registry learned from attempt 1 is reused.

    Max 2 URLs tried per domain total.
    """
    from app.utils.audit import INFO, WARNING, write_audit
    from urllib.parse import urlparse

    log.info("smart_domain_batch.start", primary_job_id=primary_job_id)

    # ─── Step 1: run the primary job ────────────────────────────────
    result = process_job_task(primary_job_id, force_strategy=force_strategy, force_model=force_model)
    log.info("smart_domain_batch.primary_done", result=result)

    # ─── Step 2: find failed domains that have backup URLs ──────────
    db = SessionLocal()
    try:
        primary_job = db.query(Job).filter(Job.id == primary_job_id).first()
        if not primary_job:
            return {"error": "primary job not found"}

        failed_domains: dict[str, str] = {}   # domain → backup_url
        for item in primary_job.items:
            if item.status != JobStatus.SUCCESS.value:
                domain = urlparse(item.url).netloc
                backup = backup_map.get(domain)
                if backup:
                    failed_domains[domain] = backup
                    write_audit(
                        "smart_domain_batch.fallback_queued",
                        f"Primary failed for {domain} — queuing backup URL",
                        level=WARNING,
                        job_id=primary_job_id,
                        domain=domain,
                        url=backup,
                    )

        if not failed_domains:
            write_audit(
                "smart_domain_batch.complete",
                f"All {primary_job.total_urls} primary URLs succeeded — no fallback needed",
                level=INFO,
                job_id=primary_job_id,
            )
            return {
                "primary_job_id": primary_job_id,
                "fallback_job_id": None,
                "fallback_domains": 0,
                "status": "all_primary_succeeded",
            }

        # ─── Step 3: create fallback job ─────────────────────────────
        fallback_urls = list(failed_domains.values())
        fallback_job = Job(
            submitted_by=f"smart-domain-fallback:{submitted_by or 'auto'}",
            total_urls=len(fallback_urls),
            status=JobStatus.PENDING.value,
        )
        db.add(fallback_job)
        db.flush()

        for url in fallback_urls:
            db.add(JobItem(
                job_id=fallback_job.id,
                url=url,
                domain=urlparse(url).netloc,
                status=JobStatus.PENDING.value,
            ))

        db.commit()
        db.refresh(fallback_job)

        write_audit(
            "smart_domain_batch.fallback_job_created",
            f"Fallback job {fallback_job.id} created for {len(failed_domains)} domain(s)",
            level=INFO,
            job_id=fallback_job.id,
            metadata={"domains": list(failed_domains.keys()), "primary_job": primary_job_id},
        )

    finally:
        db.close()

    # Run fallback job synchronously in this worker
    fallback_result = process_job_task(fallback_job.id, force_strategy=force_strategy, force_model=force_model)
    log.info("smart_domain_batch.fallback_done", result=fallback_result)

    return {
        "primary_job_id": primary_job_id,
        "fallback_job_id": fallback_job.id,
        "fallback_domains": len(failed_domains),
        "failed_domains": list(failed_domains.keys()),
        "status": "complete",
    }


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

    t0 = time.time()
    try:
        outcome = asyncio.run(
            run_agent(agent_name=agent_name, url=url, max_steps=max_steps or 30, model_name=model_name)
        )
    except Exception as e:  # noqa: BLE001
        log.exception("cua.task.failed")
        db.close()
        return {"error": str(e)}

    import os
    downloaded_filenames = [os.path.basename(f) for f in outcome.downloaded_files]
    row = AgentRun(
        agent_name=agent_name,
        url=url,
        steps=outcome.steps,
        success=outcome.success,
        runtime_seconds=time.time() - t0,
        cost_usd=outcome.cost_usd,
        trace={
            "steps": outcome.trace[:50],
            "downloaded_files": downloaded_filenames
        },
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
# Crash-recovery: rescue zombie jobs left in running/pending state
# --------------------------------------------------------------------

@celery_app.task(name="app.workers.tasks.crash_recovery_task")
def crash_recovery_task() -> dict:
    """
    Runs every 10 minutes via Celery beat.

    Detects jobs that have been stuck in 'running' for more than
    30 minutes (indicating the worker crashed mid-execution) and
    automatically re-enqueues them so they are retried without
    operator intervention.

    Items that individually failed are left alone — only whole jobs
    stuck in 'running' are rescued.
    """
    import datetime
    from app.models import JobItem
    from app.utils.audit import CRITICAL, WARNING, write_audit

    db = SessionLocal()
    rescued = 0
    aborted = 0
    threshold = datetime.datetime.utcnow() - datetime.timedelta(minutes=30)
    log.info("crash_recovery.tick")

    try:
        stuck_jobs = (
            db.query(Job)
            .filter(Job.status == JobStatus.RUNNING.value)
            .filter(Job.updated_at < threshold)
            .all()
        )

        for job in stuck_jobs:
            log.warning("crash_recovery.stuck_job_detected", job_id=job.id)
            write_audit(
                event_type="crash_recovery.rescued",
                message=f"Job {job.id} was stuck in 'running' for >30 min — re-enqueuing",
                level=WARNING,
                job_id=job.id,
                metadata={"stuck_since": str(job.updated_at)},
            )
            # Reset the job and all pending/running items
            job.status = JobStatus.PENDING.value
            for item in job.items:
                if item.status in (JobStatus.RUNNING.value, JobStatus.PENDING.value):
                    item.status = JobStatus.PENDING.value
                    item.error_message = "[CRASH-RECOVERY] Auto-rescued from stuck state"
            db.commit()
            process_job_task.delay(job.id)
            rescued += 1

        # Also mark jobs that have been PENDING for >2 hours without a worker
        # picking them up — this indicates queue overflow or worker crash.
        lost_threshold = datetime.datetime.utcnow() - datetime.timedelta(hours=2)
        lost_jobs = (
            db.query(Job)
            .filter(Job.status == JobStatus.PENDING.value)
            .filter(Job.updated_at < lost_threshold)
            .all()
        )
        for job in lost_jobs:
            log.error("crash_recovery.lost_job_aborted", job_id=job.id)
            write_audit(
                event_type="crash_recovery.lost_job",
                message=f"Job {job.id} was pending for >2h with no worker — marked failed",
                level=CRITICAL,
                job_id=job.id,
            )
            job.status = JobStatus.FAILED.value
            for item in job.items:
                if item.status == JobStatus.PENDING.value:
                    item.status = JobStatus.FAILED.value
                    item.error_message = "[CRASH-RECOVERY] No worker picked up job in 2h"
            db.commit()
            aborted += 1

        return {"rescued": rescued, "aborted": aborted}
    finally:
        db.close()


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
