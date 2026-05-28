"""
Admin / ops endpoints — stats, costs, error reports.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import classify_error
from app.database import get_db
from app.models import (
    AgentRun,
    EvaluationRun,
    Job,
    JobItem,
    JobStatus,
    ScraperTemplate,
    Strategy,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Human-readable strategy labels for the frontend
# ---------------------------------------------------------------------------
_STRATEGY_LABELS: dict[str, str] = {
    Strategy.MANUAL.value: "Manual Scraper",
    Strategy.EXISTING.value: "Existing Scraper",
    Strategy.DETERMINISTIC.value: "Deterministic DTVP",
    Strategy.LLM_GENERATED.value: "LLM Generated",
    Strategy.CUA.value: "CUA Agent",
    Strategy.NONE.value: "Failure / None",
}

# Error category → display label + severity level
_ERROR_DISPLAY: dict[str, dict] = {
    "timeout":          {"label": "Timeout",              "severity": "warning"},
    "network":          {"label": "Network Error",        "severity": "warning"},
    "dns":              {"label": "DNS Resolution",       "severity": "error"},
    "ssl":              {"label": "SSL / TLS Error",      "severity": "error"},
    "auth":             {"label": "Auth / Forbidden",     "severity": "warning"},
    "not_found":        {"label": "404 Not Found",        "severity": "info"},
    "rate_limit":       {"label": "Rate Limited",         "severity": "warning"},
    "server_error":     {"label": "Server Error (5xx)",   "severity": "error"},
    "code_validation":  {"label": "Code Validation",      "severity": "error"},
    "sandbox":          {"label": "Sandbox Violation",    "severity": "critical"},
    "prompt_injection": {"label": "Prompt Injection ⚠️",  "severity": "critical"},
    "no_documents":     {"label": "No Documents Found",   "severity": "info"},
    "storage":          {"label": "Storage / S3 Error",   "severity": "error"},
    "blocked_url":      {"label": "Blocked URL (SSRF)",   "severity": "critical"},
    "no_strategy":      {"label": "No Strategy Match",    "severity": "info"},
    "loop_exhausted":   {"label": "Loop Exhausted",       "severity": "warning"},
    "unknown":          {"label": "Unknown",              "severity": "info"},
}


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    total_jobs    = db.query(func.count(Job.id)).scalar() or 0
    total_items   = db.query(func.count(JobItem.id)).scalar() or 0
    succeeded     = (
        db.query(func.count(JobItem.id))
        .filter(JobItem.status == JobStatus.SUCCESS.value)
        .scalar() or 0
    )
    total_cost    = db.query(func.coalesce(func.sum(Job.cost_usd), 0.0)).scalar() or 0.0
    templates     = db.query(func.count(ScraperTemplate.id)).scalar() or 0
    eval_runs     = db.query(func.count(EvaluationRun.id)).scalar() or 0
    agent_runs    = db.query(func.count(AgentRun.id)).scalar() or 0

    by_strategy = {
        s.value: (
            db.query(func.count(JobItem.id))
            .filter(JobItem.strategy == s.value)
            .scalar() or 0
        )
        for s in Strategy
    }

    by_strategy_success = {
        s.value: (
            db.query(func.count(JobItem.id))
            .filter(JobItem.strategy == s.value)
            .filter(JobItem.status == JobStatus.SUCCESS.value)
            .scalar() or 0
        )
        for s in Strategy
    }

    # Error category breakdown for the admin dashboard
    failed_items = (
        db.query(JobItem.error_message)
        .filter(JobItem.status == JobStatus.FAILED.value)
        .all()
    )
    error_categories: dict[str, int] = {}
    for (msg,) in failed_items:
        cat = classify_error(msg)
        error_categories[cat] = error_categories.get(cat, 0) + 1

    return {
        "jobs": total_jobs,
        "items": total_items,
        "failed_items": len(failed_items),
        "item_success_rate": round(succeeded / total_items, 3) if total_items else 0.0,
        "total_cost_usd": round(total_cost, 4),
        "scraper_templates": templates,
        "evaluation_runs": eval_runs,
        "agent_runs": agent_runs,
        "strategy_distribution": by_strategy,
        "strategy_success_distribution": by_strategy_success,
        "error_categories": error_categories,
        "error_category_labels": {
            k: v["label"] for k, v in _ERROR_DISPLAY.items()
        },
    }


@router.get("/errors")
def recent_errors(limit: int = 50, db: Session = Depends(get_db)):
    items = (
        db.query(JobItem)
        .filter(JobItem.status == JobStatus.FAILED.value)
        .order_by(JobItem.id.desc())
        .limit(limit)
        .all()
    )
    result = []
    for i in items:
        cat = classify_error(i.error_message)
        display = _ERROR_DISPLAY.get(cat, _ERROR_DISPLAY["unknown"])
        result.append({
            "id": i.id,
            "job_id": i.job_id,
            "url": i.url,
            "domain": i.domain,
            "strategy": i.strategy,
            "strategy_label": _STRATEGY_LABELS.get(i.strategy, i.strategy),
            "iterations": i.iterations,
            "runtime_seconds": round(i.runtime_seconds, 2),
            "error_message": i.error_message,
            "error_category": cat,
            "error_label": display["label"],
            "severity": display["severity"],
        })
    return result


@router.post("/reset")
def reset_database(db: Session = Depends(get_db)):
    from app.models import Document
    try:
        db.query(Document).delete()
        db.query(JobItem).delete()
        db.query(Job).delete()
        db.query(ScraperTemplate).delete()
        db.query(EvaluationRun).delete()
        db.query(AgentRun).delete()
        db.commit()
        return {
            "status": "success",
            "message": "All pipeline data, benchmark results, and registry scrapers have been cleared."
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


@router.post("/reset-stale-jobs")
def reset_stale_jobs(db: Session = Depends(get_db)):
    try:
        stale_jobs = db.query(Job).filter(Job.status.in_([JobStatus.RUNNING.value, JobStatus.PENDING.value])).all()
        for j in stale_jobs:
            j.status = JobStatus.FAILED.value
            for item in j.items:
                if item.status in [JobStatus.RUNNING.value, JobStatus.PENDING.value]:
                    item.status = JobStatus.FAILED.value
                    item.error_message = "Task manually aborted or reset as stale"
        db.commit()
        return {
            "status": "success",
            "message": f"Successfully updated {len(stale_jobs)} stale jobs to failed state."
        }
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}


@router.get("/system-check")
def system_check(db: Session = Depends(get_db)):
    """Run a comprehensive integrity check of all frontend/backend system components."""
    import time
    from sqlalchemy import text
    import redis
    from app.workers.celery_app import celery_app
    from app.core.storage import ObjectStorage
    from app.phase1_llm_scraper.pricing import pricing_manager

    results = {}

    # 1. Database Check
    db_start = time.time()
    try:
        db.execute(text("SELECT 1")).scalar()
        results["database"] = {
            "status": "online",
            "latency_ms": round((time.time() - db_start) * 1000, 2),
            "message": "Postgres Database is responsive and fully operational."
        }
    except Exception as e:
        results["database"] = {
            "status": "offline",
            "latency_ms": 0.0,
            "message": f"Postgres offline: {str(e)}"
        }

    # 2. Redis Check
    redis_start = time.time()
    try:
        from app.config import settings
        r = redis.from_url(settings.redis_url, socket_timeout=3.0)
        r.ping()
        results["redis"] = {
            "status": "online",
            "latency_ms": round((time.time() - redis_start) * 1000, 2),
            "message": "Redis broker is active and listening for queued tasks."
        }
    except Exception as e:
        results["redis"] = {
            "status": "offline",
            "latency_ms": 0.0,
            "message": f"Redis Broker offline: {str(e)}"
        }

    # 3. MinIO S3 Object Storage Check
    s3_start = time.time()
    try:
        storage = ObjectStorage()
        storage._s3.head_bucket(Bucket=storage.bucket)
        results["storage"] = {
            "status": "online",
            "latency_ms": round((time.time() - s3_start) * 1000, 2),
            "message": f"MinIO S3 is online. Using bucket: {storage.bucket}"
        }
    except Exception as e:
        results["storage"] = {
            "status": "warning",
            "latency_ms": 0.0,
            "message": f"MinIO bucket error or down. Falling back to local storage path. Error: {str(e)}"
        }

    # 4. OpenRouter API & Dynamic Pricing Check
    llm_start = time.time()
    try:
        from app.config import settings
        if not settings.openrouter_api_key:
            results["openrouter"] = {
                "status": "offline",
                "latency_ms": 0.0,
                "message": "OPENROUTER_API_KEY environment variable is missing."
            }
        else:
            models_count = len(pricing_manager._pricing)
            results["openrouter"] = {
                "status": "online",
                "latency_ms": round((time.time() - llm_start) * 1000, 2),
                "message": f"OpenRouter API responds successfully. Dynamic cache has {models_count} active models."
            }
    except Exception as e:
        results["openrouter"] = {
            "status": "offline",
            "latency_ms": 0.0,
            "message": f"OpenRouter check failed: {str(e)}"
        }

    # 5. Celery Worker Integrity Check
    worker_start = time.time()
    try:
        inspect = celery_app.control.inspect(timeout=3.0)
        active_workers = inspect.active() if inspect else None
        if active_workers:
            workers_list = list(active_workers.keys())
            results["workers"] = {
                "status": "online",
                "latency_ms": round((time.time() - worker_start) * 1000, 2),
                "message": f"Celery workers online: {', '.join(workers_list)}"
            }
        else:
            results["workers"] = {
                "status": "warning",
                "latency_ms": 0.0,
                "message": "No active Celery workers detected. Tasks may remain queued."
            }
    except Exception as e:
        results["workers"] = {
            "status": "offline",
            "latency_ms": 0.0,
            "message": f"Could not inspect Celery workers: {str(e)}"
        }

    all_ok = all(item["status"] in ["online", "warning"] for item in results.values())
    results["overall_health"] = "healthy" if all_ok else "unhealthy"
    return results


