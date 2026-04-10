"""
Phase 2 CUA endpoints.

POST /api/agents/run   → kick off a CUA run against a single URL
GET  /api/agents/runs  → list historical agent runs
GET  /api/agents/summary → aggregated metrics per agent
"""
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AgentRun
from app.schemas import AgentRunRead, AgentRunRequest
from app.workers.tasks import run_cua_task

router = APIRouter()


@router.post("/run", status_code=202)
def trigger_cua(payload: AgentRunRequest):
    task = run_cua_task.delay(
        agent_name=payload.agent_name,
        url=str(payload.url),
        max_steps=payload.max_steps,
    )
    return {"task_id": task.id, "status": "queued"}


@router.get("/runs", response_model=list[AgentRunRead])
def list_agent_runs(limit: int = 100, db: Session = Depends(get_db)):
    return db.query(AgentRun).order_by(AgentRun.created_at.desc()).limit(limit).all()


@router.get("/summary")
def agent_summary(db: Session = Depends(get_db)):
    runs = db.query(AgentRun).all()
    per_agent: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "successes": 0, "steps": 0, "runtime": 0.0, "cost": 0.0}
    )
    for r in runs:
        a = per_agent[r.agent_name]
        a["total"] += 1
        a["successes"] += int(r.success)
        a["steps"] += r.steps
        a["runtime"] += r.runtime_seconds
        a["cost"] += r.cost_usd

    out = []
    for name, s in per_agent.items():
        n = max(s["total"], 1)
        out.append({
            "agent": name,
            "runs": s["total"],
            "success_rate": round(s["successes"] / n, 3),
            "avg_steps": round(s["steps"] / n, 2),
            "avg_runtime_s": round(s["runtime"] / n, 2),
            "total_cost_usd": round(s["cost"], 4),
        })
    out.sort(key=lambda x: x["success_rate"], reverse=True)
    return out
