"""
Audit-log API endpoints.

GET  /api/audit                 → paginated list of recent audit events
GET  /api/audit/jobs/{job_id}   → all events for a specific job
GET  /api/audit/stats           → aggregate counts by level + event_type
DELETE /api/audit               → purge audit log (admin only)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog
from app.schemas import AuditLogRead

router = APIRouter()


@router.get("", response_model=list[AuditLogRead])
def list_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    level: str | None = Query(None),
    event_type: str | None = Query(None),
    job_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(AuditLog).order_by(AuditLog.created_at.desc())
    if level:
        q = q.filter(AuditLog.level == level)
    if event_type:
        q = q.filter(AuditLog.event_type.ilike(f"%{event_type}%"))
    if job_id:
        q = q.filter(AuditLog.job_id == job_id)
    return q.offset(offset).limit(limit).all()


@router.get("/jobs/{job_id}", response_model=list[AuditLogRead])
def audit_for_job(job_id: str, db: Session = Depends(get_db)):
    return (
        db.query(AuditLog)
        .filter(AuditLog.job_id == job_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )


@router.get("/stats")
def audit_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(AuditLog.id)).scalar() or 0

    by_level = dict(
        db.query(AuditLog.level, func.count(AuditLog.id))
        .group_by(AuditLog.level)
        .all()
    )

    # Top 15 event types by frequency
    by_event = [
        {"event_type": et, "count": cnt}
        for et, cnt in (
            db.query(AuditLog.event_type, func.count(AuditLog.id))
            .group_by(AuditLog.event_type)
            .order_by(func.count(AuditLog.id).desc())
            .limit(15)
            .all()
        )
    ]

    return {"total": total, "by_level": by_level, "by_event_type": by_event}


@router.delete("", status_code=204)
def purge_audit_log(db: Session = Depends(get_db)):
    db.query(AuditLog).delete()
    db.commit()
