"""
Admin / ops endpoints — stats, costs, error reports.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AgentRun, EvaluationRun, Job, JobItem, JobStatus, ScraperTemplate, Strategy

router = APIRouter()


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    total_jobs    = db.query(func.count(Job.id)).scalar() or 0
    total_items   = db.query(func.count(JobItem.id)).scalar() or 0
    succeeded     = db.query(func.count(JobItem.id)).filter(JobItem.status == JobStatus.SUCCESS).scalar() or 0
    total_cost    = db.query(func.coalesce(func.sum(Job.cost_usd), 0.0)).scalar() or 0.0
    templates     = db.query(func.count(ScraperTemplate.id)).scalar() or 0
    eval_runs     = db.query(func.count(EvaluationRun.id)).scalar() or 0
    agent_runs    = db.query(func.count(AgentRun.id)).scalar() or 0

    by_strategy = {
        s.value: db.query(func.count(JobItem.id)).filter(JobItem.strategy == s).scalar() or 0
        for s in Strategy
    }

    return {
        "jobs": total_jobs,
        "items": total_items,
        "item_success_rate": round(succeeded / total_items, 3) if total_items else 0.0,
        "total_cost_usd": round(total_cost, 4),
        "scraper_templates": templates,
        "evaluation_runs": eval_runs,
        "agent_runs": agent_runs,
        "strategy_distribution": by_strategy,
    }


@router.get("/errors")
def recent_errors(limit: int = 50, db: Session = Depends(get_db)):
    items = (
        db.query(JobItem)
        .filter(JobItem.status == JobStatus.FAILED)
        .order_by(JobItem.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": i.id,
            "job_id": i.job_id,
            "url": i.url,
            "strategy": i.strategy.value,
            "iterations": i.iterations,
            "error_message": i.error_message,
        }
        for i in items
    ]
