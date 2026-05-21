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

