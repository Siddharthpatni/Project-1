"""
Evaluation endpoints — Phase 1 LLM benchmark + Phase 3 pipeline analytics.

POST /api/evaluation/run          → trigger LLM benchmark on a dataset
GET  /api/evaluation/runs         → list historical LLM benchmark runs
GET  /api/evaluation/summary      → aggregated LLM metrics per model
GET  /api/evaluation/pipeline     → real pipeline strategy performance from job data
GET  /api/evaluation/scraper-health → scraper registry quality report
"""
from collections import defaultdict
from urllib.parse import urlparse

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EvaluationRun, Job, JobItem, JobStatus, ScraperTemplate, Strategy
from app.schemas import EvaluationRequest, EvaluationRunRead
from app.workers.tasks import run_evaluation_task

router = APIRouter()

# Human labels for strategy keys
_STRATEGY_LABELS = {
    "existing_scraper":       "Existing (Cached)",
    "deterministic_template": "Deterministic",
    "adaptive_universal":     "Universal Adaptive",
    "llm_generated_scraper":  "LLM Generated",
    "learned_route":          "Learned Route",
    "computer_use_agent":     "CUA Fallback",
    "manual_scraper":         "Manual (V1)",
    "none":                   "All Failed",
}


# ---------------------------------------------------------------------------
# Phase 1 LLM Benchmark
# ---------------------------------------------------------------------------

@router.post("/run", status_code=202)
def trigger_evaluation(payload: EvaluationRequest):
    task = run_evaluation_task.delay(
        dataset_path=payload.dataset_path,
        models=payload.models,
        max_iterations=payload.max_iterations,
    )
    return {"task_id": task.id, "status": "queued"}


@router.get("/runs", response_model=list[EvaluationRunRead])
def list_runs(limit: int = 200, db: Session = Depends(get_db)):
    return (
        db.query(EvaluationRun)
        .order_by(EvaluationRun.created_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/summary")
def evaluation_summary(db: Session = Depends(get_db)):
    """Per-model: success rate, avg iterations, avg cost, avg runtime."""
    runs = db.query(EvaluationRun).all()
    per_model: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "successes": 0, "iterations": 0, "runtime": 0.0, "cost": 0.0}
    )
    for r in runs:
        m = per_model[r.model]
        m["total"] += 1
        m["successes"] += int(r.success)
        m["iterations"] += r.iterations
        m["runtime"] += r.runtime_seconds
        m["cost"] += r.cost_usd

    summary = []
    for model, s in per_model.items():
        n = max(s["total"], 1)
        summary.append({
            "model":           model,
            "runs":            s["total"],
            "success_rate":    round(s["successes"] / n, 3),
            "avg_iterations":  round(s["iterations"] / n, 2),
            "avg_runtime_s":   round(s["runtime"] / n, 2),
            "total_cost_usd":  round(s["cost"], 4),
        })
    summary.sort(key=lambda x: x["success_rate"], reverse=True)
    return summary


# ---------------------------------------------------------------------------
# Phase 3 Pipeline Analytics — derived from real job execution data
# ---------------------------------------------------------------------------

@router.get("/pipeline")
def pipeline_stats(db: Session = Depends(get_db)):
    """
    Real pipeline performance aggregated from all completed job items.

    Returns:
      - by_strategy:  success rate, avg runtime, total cost, item count per strategy
      - by_platform:  success rate and dominant strategy per detected platform
      - by_failure:   failure category counts (top 15)
      - totals:       headline KPIs
    """
    items = db.query(JobItem).filter(
        JobItem.status.in_([JobStatus.SUCCESS.value, JobStatus.FAILED.value])
    ).all()

    if not items:
        return {
            "by_strategy": [], "by_attempts": [], "by_platform": [], "by_failure": [],
            "totals": {"total": 0, "success": 0, "success_rate": 0, "total_cost": 0},
        }

    # ── By strategy ──────────────────────────────────────────────────────────
    strat_buckets: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "success": 0, "runtime_sum": 0.0, "cost_sum": 0.0}
    )
    for item in items:
        s = item.strategy or "none"
        b = strat_buckets[s]
        b["total"] += 1
        b["success"] += 1 if item.status == JobStatus.SUCCESS.value else 0
        b["runtime_sum"] += item.runtime_seconds or 0.0

    # Cost is at job level; we approximate from runtime ratio
    jobs = db.query(Job).filter(Job.cost_usd > 0).all()
    job_cost_map = {j.id: j.cost_usd for j in jobs}
    for item in items:
        job_cost = job_cost_map.get(item.job_id, 0.0)
        job_total = db.query(func.count(JobItem.id)).filter(JobItem.job_id == item.job_id).scalar() or 1
        strat_buckets[item.strategy or "none"]["cost_sum"] += job_cost / job_total

    by_strategy = []
    for strat, b in sorted(strat_buckets.items(), key=lambda x: -x[1]["success"]):
        n = max(b["total"], 1)
        by_strategy.append({
            "strategy":       strat,
            "label":          _STRATEGY_LABELS.get(strat, strat.replace("_", " ").title()),
            "total":          b["total"],
            "success":        b["success"],
            "success_rate":   round(b["success"] / n, 3),
            "avg_runtime_s":  round(b["runtime_sum"] / n, 2),
            "total_cost_usd": round(b["cost_sum"], 4),
        })

    # ── By platform (derived from domain + strategy used) ────────────────────
    platform_buckets: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "success": 0, "strategies": defaultdict(int)}
    )
    for item in items:
        # Classify domain → platform using URL classifier
        try:
            from app.phase3_integration.platform_classifier import classify_url
            platform = classify_url(item.url) if item.url else "unknown"
        except Exception:
            platform = "unknown"

        pb = platform_buckets[platform]
        pb["total"] += 1
        pb["success"] += 1 if item.status == JobStatus.SUCCESS.value else 0
        pb["strategies"][item.strategy or "none"] += 1

    by_platform = []
    for platform, pb in sorted(platform_buckets.items(), key=lambda x: -x[1]["total"]):
        n = max(pb["total"], 1)
        dominant = max(pb["strategies"].items(), key=lambda x: x[1])[0] if pb["strategies"] else "none"
        by_platform.append({
            "platform":         platform,
            "total":            pb["total"],
            "success":          pb["success"],
            "success_rate":     round(pb["success"] / n, 3),
            "dominant_strategy": dominant,
            "dominant_label":   _STRATEGY_LABELS.get(dominant, dominant),
        })
    by_platform.sort(key=lambda x: -x["total"])

    # ── Attempt-level success ratio per strategy ──────────────────────────────
    # by_strategy above only counts each item's WINNING strategy, which biases
    # the picture toward CUA/EXISTING. This counts every attempt in every
    # cascade, so MANUAL / DETERMINISTIC / LLM_GENERATED get an honest
    # success ratio even when a later strategy took the win.
    attempt_buckets: dict[str, dict] = defaultdict(
        lambda: {"attempts": 0, "successes": 0, "duration_sum": 0.0}
    )
    for item in items:
        for a in (item.attempts_detail or []):
            b = attempt_buckets[a.get("strategy") or "none"]
            b["attempts"] += 1
            b["successes"] += 1 if a.get("success") else 0
            try:
                b["duration_sum"] += float(a.get("duration_s") or 0.0)
            except (TypeError, ValueError):
                pass

    by_attempts = []
    for strat, b in sorted(attempt_buckets.items(), key=lambda x: -x[1]["attempts"]):
        n = max(b["attempts"], 1)
        by_attempts.append({
            "strategy":       strat,
            "label":          _STRATEGY_LABELS.get(strat, strat.replace("_", " ").title()),
            "attempts":       b["attempts"],
            "successes":      b["successes"],
            "success_ratio":  round(b["successes"] / n, 3),
            "avg_duration_s": round(b["duration_sum"] / n, 2),
        })

    # ── By failure category ───────────────────────────────────────────────────
    fail_counts: dict[str, int] = defaultdict(int)
    for item in items:
        if item.status == JobStatus.FAILED.value and item.failure_category:
            fail_counts[item.failure_category] += 1

    by_failure = [
        {"category": cat, "count": cnt}
        for cat, cnt in sorted(fail_counts.items(), key=lambda x: -x[1])[:15]
    ]

    # ── Totals ────────────────────────────────────────────────────────────────
    total   = len(items)
    success = sum(1 for i in items if i.status == JobStatus.SUCCESS.value)
    total_cost = sum(job_cost_map.values())

    return {
        "by_strategy": by_strategy,
        "by_attempts": by_attempts,
        "by_platform": by_platform,
        "by_failure":  by_failure,
        "totals": {
            "total":        total,
            "success":      success,
            "failed":       total - success,
            "success_rate": round(success / max(total, 1), 3),
            "total_cost_usd": round(total_cost, 4),
        },
    }


@router.get("/scraper-health")
def scraper_health(db: Session = Depends(get_db)):
    """
    Scraper registry quality report.

    For each registered domain scraper:
      - Total executions (success + failure counts)
      - Success rate
      - Health status: healthy (≥70%), degraded (20-70%), retiring (<20% after 10+ runs)
      - Source: disk | llm | manual | cua
    """
    from app.phase3_integration.scraper_registry import should_retire

    templates = db.query(ScraperTemplate).order_by(ScraperTemplate.success_count.desc()).all()

    results = []
    for tpl in templates:
        total = tpl.success_count + tpl.failure_count
        rate  = (tpl.success_count / total) if total > 0 else None
        retiring = should_retire(tpl)

        if rate is None:
            health = "untested"
        elif retiring:
            health = "retiring"
        elif rate >= 0.7:
            health = "healthy"
        elif rate >= 0.2:
            health = "degraded"
        else:
            health = "retiring"

        results.append({
            "domain":          tpl.domain,
            "source":          tpl.source,
            "platform":        tpl.platform,
            "route_used":      tpl.route_used,
            "success_count":   tpl.success_count,
            "failure_count":   tpl.failure_count,
            "total_runs":      total,
            "success_rate":    round(rate, 3) if rate is not None else None,
            "avg_runtime_s":   round(tpl.avg_runtime, 2),
            "health":          health,
            "has_cua_hint":    bool(tpl.cua_hint),
            "created_at":      tpl.created_at.isoformat(),
            "updated_at":      tpl.updated_at.isoformat(),
        })

    healthy   = sum(1 for r in results if r["health"] == "healthy")
    degraded  = sum(1 for r in results if r["health"] == "degraded")
    retiring  = sum(1 for r in results if r["health"] == "retiring")
    untested  = sum(1 for r in results if r["health"] == "untested")

    return {
        "scrapers":  results,
        "summary": {
            "total":    len(results),
            "healthy":  healthy,
            "degraded": degraded,
            "retiring": retiring,
            "untested": untested,
        },
    }
