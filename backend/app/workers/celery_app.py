"""
Celery application with Redis broker + result backend.

Beat schedule runs the periodic document-versioning check once per day
(interval configurable via VERSIONING_CHECK_INTERVAL_HOURS).
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
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_max_tasks_per_child=50,
    worker_prefetch_multiplier=1,
    timezone="UTC",
)

celery_app.conf.beat_schedule = {
    "check-document-versions": {
        "task": "app.workers.tasks.check_document_versions_task",
        "schedule": crontab(hour="*/{}".format(settings.versioning_check_interval_hours), minute=0),
    },
}
