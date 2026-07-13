"""
Centralised audit-log writer.

Every meaningful pipeline event should flow through `write_audit()` so
ops can reconstruct the exact sequence of events for any job, URL, or
security incident without parsing raw application logs.

Design constraints
------------------
- Fire-and-forget: the writer catches all DB exceptions so a log failure
  never aborts the calling business logic.
- Thread-safe: uses the SessionLocal factory, not the caller's session,
  to avoid cross-thread session sharing.
- Lightweight: one DB insert per call — no buffering, no background thread.
  Volume is bounded by the pipeline step count, which is always small.
"""
from __future__ import annotations

import traceback
from datetime import datetime, UTC
from typing import Any

from app.utils.logger import get_logger

log = get_logger(__name__)

# Level constants — mirrors Python logging levels for familiarity
INFO     = "info"
WARNING  = "warning"
ERROR    = "error"
CRITICAL = "critical"


def write_audit(
    event_type: str,
    message: str,
    level: str = INFO,
    job_id: str | None = None,
    item_id: str | None = None,
    domain: str | None = None,
    url: str | None = None,
    strategy: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Insert one row into audit_logs. Never raises."""
    try:
        from app.database import SessionLocal
        from app.models import AuditLog

        row = AuditLog(
            created_at=datetime.now(UTC),
            level=level,
            event_type=event_type,
            job_id=job_id,
            item_id=item_id,
            domain=domain,
            url=url,
            strategy=strategy,
            message=message[:4000],
            extra=metadata or {},
        )
        db = SessionLocal()
        try:
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        # Log to structlog but never propagate — audit failures must not
        # interrupt the pipeline.
        log.warning("audit.write_failed", event_type=event_type, tb=traceback.format_exc()[-300:])
