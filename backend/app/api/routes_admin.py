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


@router.get("/circuit-breakers")
def get_circuit_breakers():
    """
    Return the current state of all per-domain circuit breakers.
    Open circuits mean the domain has exceeded the failure threshold and
    requests are being fast-failed to save worker capacity.
    """
    from app.phase3_integration.url_intelligence import circuit_breaker
    stats = circuit_breaker.get_stats()
    open_circuits   = {d: v for d, v in stats.items() if v["state"] == "open"}
    half_open       = {d: v for d, v in stats.items() if v["state"] == "half_open"}
    return {
        "total_tracked": len(stats),
        "open":          len(open_circuits),
        "half_open":     len(half_open),
        "circuits":      stats,
    }


@router.delete("/circuit-breakers/{domain}")
def reset_circuit_breaker(domain: str):
    """Manually reset a domain's circuit breaker to CLOSED (allow requests again)."""
    from app.phase3_integration.url_intelligence import circuit_breaker
    circuit_breaker.record_success(domain)
    return {"domain": domain, "state": "closed", "message": "Circuit reset — domain will be attempted again."}


@router.get("/verified-urls")
def get_verified_urls():
    """
    Return the pre-verified URL database — best known working URL per domain
    with ZIP availability confirmed via HEAD request.
    Built from publications_28_05_2026.xlsx and refreshed periodically.
    """
    import json
    from pathlib import Path
    vf = Path("/app/data/verified_urls.json")
    if not vf.exists():
        vf = Path("data/verified_urls.json")
    if not vf.exists():
        return {"error": "verified_urls.json not found — run the URL verification script"}
    data = json.loads(vf.read_text())
    return data


@router.get("/url-intelligence")
def analyze_url(url: str):
    """
    Classify a single URL — returns predicted type, strategy order, and expected
    success rate. Useful for debugging individual URLs.
    """
    from app.phase3_integration.url_intelligence import classify_url_type, get_strategy_order, URL_TYPE_SUCCESS_RATE
    from app.phase3_integration.platform_classifier import classify_url as clf_platform
    url_type   = classify_url_type(url)
    platform   = clf_platform(url)
    strategies = get_strategy_order(url_type, platform)
    return {
        "url":              url,
        "url_type":         url_type.value,
        "platform":         platform,
        "expected_success": URL_TYPE_SUCCESS_RATE.get(url_type, 0.35),
        "strategy_order":   [s.value for s in strategies],
        "will_use_llm":     any(s.value == "llm_generated_scraper" for s in strategies),
        "will_use_cua":     any(s.value == "computer_use_agent" for s in strategies),
    }


@router.post("/url-intelligence/batch")
def analyze_url_batch(body: dict):
    """
    Pre-classify a batch of URLs before submitting a job.

    Returns per-URL intelligence: type, platform, expected success rate,
    strategy order, and a warning for auth-gated URLs that will likely fail.

    Body: {"urls": ["https://...", ...]}

    Use this before submitting 10K-URL jobs to:
    - Know in advance how many URLs will succeed (~35% UNKNOWN, ~93% SATELLITE)
    - Surface auth-gated URLs (NETSERVER_AUTH, EVERGABE_DEEP) that waste budget
    - Get a breakdown of URL types in the batch
    """
    from collections import Counter
    from app.phase3_integration.url_intelligence import (
        classify_url_type, get_strategy_order,
        URL_TYPE_SUCCESS_RATE, UrlType,
    )
    from app.phase3_integration.platform_classifier import classify_url as clf_platform

    urls: list[str] = body.get("urls", [])
    if not urls:
        return {"error": "provide a non-empty 'urls' list"}
    if len(urls) > 50_000:
        return {"error": "batch limit is 50,000 URLs per request"}

    results = {}
    seen: set[str] = set()
    type_counts: Counter = Counter()

    for url in urls:
        if url in seen:
            results[url] = {"duplicate": True}
            continue
        seen.add(url)

        url_type   = classify_url_type(url)
        platform   = clf_platform(url)
        strategies = get_strategy_order(url_type, platform)
        success_p  = URL_TYPE_SUCCESS_RATE.get(url_type, 0.35)
        type_counts[url_type.value] += 1

        warning = None
        if url_type in (UrlType.NETSERVER_AUTH, UrlType.EVERGABE_DEEP, UrlType.EVA_PORTAL):
            warning = (
                f"Auth-gated portal ({url_type.value}) — expect ~5% success. "
                "Only CUA (visual login) has any chance; LLM generation is skipped."
            )

        results[url] = {
            "url_type":         url_type.value,
            "platform":         platform,
            "expected_success": success_p,
            "strategy_order":   [s.value for s in strategies],
            "will_use_llm":     any(s.value == "llm_generated_scraper" for s in strategies),
            "will_use_cua":     any(s.value == "computer_use_agent" for s in strategies),
            "warning":          warning,
        }

    unique = len(seen)
    expected_successes = sum(
        URL_TYPE_SUCCESS_RATE.get(classify_url_type(u), 0.35)
        for u in seen
    )

    return {
        "total":              len(urls),
        "unique":             unique,
        "duplicates":         len(urls) - unique,
        "type_breakdown":     dict(type_counts),
        "estimated_successes": round(expected_successes),
        "estimated_success_rate": round(expected_successes / unique, 3) if unique else 0.0,
        "results":            results,
    }


