"""
Phase 1 evaluation endpoints — expose the LLM benchmark harness.

POST /api/evaluation/run    → trigger a benchmark run on a dataset
GET  /api/evaluation/runs   → list historical runs
GET  /api/evaluation/summary → aggregated metrics per model
"""
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import EvaluationRun
from app.schemas import EvaluationRequest, EvaluationRunRead
from app.workers.tasks import run_evaluation_task

router = APIRouter()


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
    """Aggregate: success rate, avg iterations, avg cost — per model."""
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
            "model": model,
            "runs": s["total"],
            "success_rate": round(s["successes"] / n, 3),
            "avg_iterations": round(s["iterations"] / n, 2),
            "avg_runtime_s": round(s["runtime"] / n, 2),
            "total_cost_usd": round(s["cost"], 4),
        })
    summary.sort(key=lambda x: x["success_rate"], reverse=True)
    return summary
