"""
FastAPI application entry point.

Wires up routers for all three phases plus admin, audit, and test endpoints.
Configures CORS for the Next.js frontend and exposes health/root checks.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    routes_agents,
    routes_admin,
    routes_audit,
    routes_evaluation,
    routes_jobs,
    routes_scrapers,
    routes_tests,
)
from app.config import settings
from app.database import Base, engine
from app.utils.logger import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("vergabepilot.starting", version="0.2.0")
    Base.metadata.create_all(bind=engine)

    # Write startup audit event
    from app.utils.audit import INFO, write_audit
    write_audit("system.startup", "Vergabepilot.AI API started — DB schema synced", level=INFO)

    # Rescue any zombie jobs left in running/pending from prior crash
    from app.database import SessionLocal
    from app.models import Job, JobStatus
    from app.utils.audit import WARNING

    db = SessionLocal()
    try:
        stale = db.query(Job).filter(
            Job.status.in_([JobStatus.RUNNING.value, JobStatus.PENDING.value])
        ).all()
        for j in stale:
            j.status = JobStatus.FAILED.value
            for item in j.items:
                if item.status in [JobStatus.RUNNING.value, JobStatus.PENDING.value]:
                    item.status = JobStatus.FAILED.value
                    item.error_message = "Interrupted: container/system restart"
            write_audit(
                "system.startup_cleanup",
                f"Rescued zombie job {j.id} on startup",
                level=WARNING,
                job_id=j.id,
            )
        db.commit()
        if stale:
            log.info("vergabepilot.startup_cleanup", count=len(stale))
    except Exception as e:
        log.error("vergabepilot.startup_cleanup_failed", error=str(e))
    finally:
        db.close()

    yield
    write_audit("system.shutdown", "Vergabepilot.AI API shutting down", level=INFO)
    log.info("vergabepilot.shutdown")


app = FastAPI(
    title="Vergabepilot.AI",
    description=(
        "Agentic AI for Automated Public Procurement Scraping. "
        "Cascaded pipeline: manual → cached → deterministic → LLM-generated → CUA fallback."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Global unhandled exception handler → writes to audit log ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    from app.utils.audit import CRITICAL, write_audit
    import traceback

    tb = traceback.format_exc()[-1500:]
    write_audit(
        event_type="system.unhandled_exception",
        message=f"{type(exc).__name__}: {exc}",
        level=CRITICAL,
        metadata={"path": str(request.url), "method": request.method, "traceback": tb},
    )
    log.error("api.unhandled_exception", path=str(request.url), exc=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )


# Routers
app.include_router(routes_jobs.router,       prefix="/api/jobs",       tags=["jobs"])
app.include_router(routes_scrapers.router,   prefix="/api/scrapers",   tags=["scrapers"])
app.include_router(routes_evaluation.router, prefix="/api/evaluation", tags=["phase1-evaluation"])
app.include_router(routes_agents.router,     prefix="/api/agents",     tags=["phase2-cua"])
app.include_router(routes_admin.router,      prefix="/api/admin",      tags=["admin"])
app.include_router(routes_audit.router,      prefix="/api/audit",      tags=["audit"])
app.include_router(routes_tests.router,      prefix="/api/tests",      tags=["tests"])


@app.get("/")
def root():
    return {
        "service": "vergabepilot.ai",
        "version": "0.2.0",
        "phases": ["phase1_llm_scraper", "phase2_cua", "phase3_integration"],
        "docs": "/docs",
    }


@app.get("/health")
def health():
    from sqlalchemy import text
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "error",
        "version": "0.2.0",
    }
