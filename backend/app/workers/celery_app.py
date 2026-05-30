"""
Celery application — optimised for 10,000+ URL scraping at scale.

Queue architecture
------------------
  default   : job orchestration (process_job_task, smart_domain_batch_task)
  chunks    : per-chunk parallel URL processing (process_chunk_task)
  cua       : computer-use agent tasks (expensive, low concurrency)
  beat      : periodic tasks (versioning check, crash recovery)

Workers are configured separately by queue so we can tune concurrency:
  - default/chunks workers: high concurrency (8–16 threads)
  - cua workers: low concurrency (1–2) — CUA is browser-heavy
"""
from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery_app = Celery(
    "vergabepilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],

    # Reliability
    task_acks_late=True,                 # Don't ack until task COMPLETES (survive worker crash)
    task_reject_on_worker_lost=True,     # Re-queue if worker dies mid-task
    worker_prefetch_multiplier=1,        # Never prefetch — critical for long-running tasks
    task_time_limit=7200,                # 2h hard kill
    task_soft_time_limit=7100,           # 2h-1s SIGTERM warning

    # Scale
    worker_max_tasks_per_child=200,      # Recycle worker after N tasks (prevent memory leaks)

    # Results
    result_expires=86400,                # Keep results 24h

    # Routing
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.process_job_task":           {"queue": "default"},
        "app.workers.tasks.process_chunk_task":         {"queue": "chunks"},
        "app.workers.tasks.run_cua_task":               {"queue": "cua"},
        "app.workers.tasks.smart_domain_batch_task":    {"queue": "default"},
        "app.workers.tasks.run_evaluation_task":        {"queue": "default"},
        "app.workers.tasks.crash_recovery_task":        {"queue": "beat"},
        "app.workers.tasks.check_document_versions_task": {"queue": "beat"},
    },

    # Timezone
    timezone="UTC",
)

celery_app.conf.beat_schedule = {
    # Auto-recovery: rescue zombie jobs every 10 minutes
    "crash-recovery": {
        "task": "app.workers.tasks.crash_recovery_task",
        "schedule": 600,
        "options": {"queue": "beat"},
    },
    # Document versioning check every N hours
    "check-document-versions": {
        "task": "app.workers.tasks.check_document_versions_task",
        "schedule": crontab(hour="*/{}".format(settings.versioning_check_interval_hours), minute=0),
        "options": {"queue": "beat"},
    },
}
