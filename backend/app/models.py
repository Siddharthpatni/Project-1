"""
SQLAlchemy ORM models.

Tables:
- Job              : a scrape request (list of URLs) submitted by a client
- JobItem          : one URL within a job, with per-URL status and strategy used
- Document         : a downloaded tender document (stored in S3)
- ScraperTemplate  : a reusable scraper (either manually written or LLM-generated)
- EvaluationRun    : a row in the phase-1 benchmark table
- AgentRun         : a row in the phase-2 CUA benchmark table
- AuditLog         : append-only structured event log for all system operations
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class JobStatus(str, PyEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class Strategy(str, PyEnum):
    MANUAL = "manual_scraper"
    EXISTING = "existing_scraper"
    DETERMINISTIC = "deterministic_template"
    LLM_GENERATED = "llm_generated_scraper"
    CUA = "computer_use_agent"
    NONE = "none"


class Job(Base):
    __tablename__ = "jobs"

    id:         Mapped[str]      = mapped_column(String, primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    status:     Mapped[str]      = mapped_column(String, default=JobStatus.PENDING.value)
    submitted_by: Mapped[str | None] = mapped_column(String, nullable=True)
    total_urls:   Mapped[int]  = mapped_column(Integer, default=0)
    completed:    Mapped[int]  = mapped_column(Integer, default=0)
    cost_usd:     Mapped[float] = mapped_column(Float, default=0.0)

    items: Mapped[list["JobItem"]] = relationship(back_populates="job", cascade="all, delete-orphan")


class JobItem(Base):
    __tablename__ = "job_items"

    id:       Mapped[str]       = mapped_column(String, primary_key=True, default=_uuid)
    job_id:   Mapped[str]       = mapped_column(ForeignKey("jobs.id"))
    url:      Mapped[str]       = mapped_column(Text)
    domain:   Mapped[str]       = mapped_column(String, index=True)
    status:   Mapped[str]       = mapped_column(String, default=JobStatus.PENDING.value)
    strategy: Mapped[str]       = mapped_column(String, default=Strategy.NONE.value)
    iterations: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_seconds: Mapped[float] = mapped_column(Float, default=0.0)

    job: Mapped[Job] = relationship(back_populates="items")
    documents: Mapped[list["Document"]] = relationship(back_populates="job_item", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id:          Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    job_item_id: Mapped[str] = mapped_column(ForeignKey("job_items.id"))
    filename:    Mapped[str] = mapped_column(String)
    s3_key:      Mapped[str] = mapped_column(String)
    mime_type:   Mapped[str] = mapped_column(String)
    size_bytes:  Mapped[int] = mapped_column(Integer, default=0)
    version:     Mapped[int] = mapped_column(Integer, default=1)
    checksum:    Mapped[str] = mapped_column(String, default="")
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    job_item: Mapped[JobItem] = relationship(back_populates="documents")


class ScraperTemplate(Base):
    """A reusable scraper keyed by domain (Phase 3 registry)."""
    __tablename__ = "scraper_templates"

    id:       Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    domain:   Mapped[str] = mapped_column(String, unique=True, index=True)
    code:     Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String, default="python")
    source:   Mapped[str] = mapped_column(String, default="llm")  # llm | manual
    platform: Mapped[str | None] = mapped_column(String, nullable=True)  # e.g. "netserver", "dtvp"
    route_used: Mapped[bool] = mapped_column(default=False)  # was route-guided generation used?
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_runtime:   Mapped[float] = mapped_column(Float, default=0.0)
    created_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EvaluationRun(Base):
    """A phase-1 benchmark row: one model × one URL × one attempt."""
    __tablename__ = "evaluation_runs"

    id:             Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    created_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    model:          Mapped[str] = mapped_column(String, index=True)
    url:            Mapped[str] = mapped_column(Text)
    expected_docs:  Mapped[int] = mapped_column(Integer, default=0)
    downloaded_docs: Mapped[int] = mapped_column(Integer, default=0)
    success:        Mapped[bool] = mapped_column(default=False)
    iterations:     Mapped[int] = mapped_column(Integer, default=0)
    runtime_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd:       Mapped[float] = mapped_column(Float, default=0.0)
    notes:          Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentRun(Base):
    """A phase-2 CUA benchmark row."""
    __tablename__ = "agent_runs"

    id:         Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    agent_name: Mapped[str] = mapped_column(String, index=True)
    url:        Mapped[str] = mapped_column(Text)
    steps:      Mapped[int] = mapped_column(Integer, default=0)
    success:    Mapped[bool] = mapped_column(default=False)
    runtime_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    cost_usd:   Mapped[float] = mapped_column(Float, default=0.0)
    trace:      Mapped[dict]  = mapped_column(JSON, default=dict)


class AuditLog(Base):
    """
    Append-only structured event log.

    Every significant pipeline event, error, recovery action, and security
    alert is written here so ops can replay the exact sequence that led to
    any outcome. Never UPDATE or DELETE rows — only INSERT.
    """
    __tablename__ = "audit_logs"

    id:          Mapped[str]      = mapped_column(String, primary_key=True, default=_uuid)
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    level:       Mapped[str]      = mapped_column(String, default="info")   # info|warning|error|critical
    event_type:  Mapped[str]      = mapped_column(String, index=True)        # pipeline.start, strategy.attempt, …
    job_id:      Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    item_id:     Mapped[str | None] = mapped_column(String, nullable=True)
    domain:      Mapped[str | None] = mapped_column(String, nullable=True)
    url:         Mapped[str | None] = mapped_column(Text,   nullable=True)
    strategy:    Mapped[str | None] = mapped_column(String, nullable=True)
    message:     Mapped[str]      = mapped_column(Text, default="")
    extra:       Mapped[dict]     = mapped_column(JSON, default=dict)        # arbitrary extra fields (metadata reserved by SQLAlchemy)
