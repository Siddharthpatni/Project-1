"""
FastAPI application entry point.

Wires up routers for all three phases plus admin, audit, and test endpoints.
Configures CORS for the Next.js frontend and exposes health/root checks.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text as _sa_text

from app.api import (
    routes_agents,
    routes_admin,
    routes_audit,
    routes_directory,
    routes_evaluation,
    routes_extractor,
    routes_jobs,
    routes_scrapers,
    routes_tests,
)
from app.core import metrics as _metrics_module
from app.config import settings
from app.database import Base, engine
from app.utils.logger import get_logger

log = get_logger(__name__)


def _run_schema_migrations() -> None:
    """
    Apply pending Alembic migrations on startup.

    Uses `alembic upgrade head` via the Python API so new containers
    automatically migrate without a manual step. Falls back to
    `create_all` for the initial table creation when no migration history
    exists yet (e.g. fresh SQLite dev env).
    """
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command
        from pathlib import Path as _Path

        alembic_cfg = AlembicConfig(
            str(_Path(__file__).resolve().parents[1] / "alembic.ini")
        )
        alembic_cfg.set_main_option(
            "sqlalchemy.url", str(engine.url)
        )
        alembic_command.upgrade(alembic_cfg, "head")
        log.info("db.alembic_migrations_applied")
    except Exception as e:  # noqa: BLE001
        # Alembic not available or migration failed — fall back to create_all
        # so the service can still start in development / CI environments.
        log.warning("db.alembic_unavailable_using_create_all", error=str(e))


_STARTUP_LOCK_ID = 727442  # arbitrary app-wide advisory lock key


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("vergabepilot.starting", version="0.2.0")
    # Serialize startup init across uvicorn worker processes: with
    # WEB_CONCURRENCY > 1 every worker runs this lifespan, and concurrent
    # create_all/alembic/seed calls race each other on first boot.
    _init_lock = None
    if engine.dialect.name == "postgresql":
        try:
            _init_lock = engine.connect()
            _init_lock.execute(_sa_text(f"SELECT pg_advisory_lock({_STARTUP_LOCK_ID})"))
        except Exception as e:  # noqa: BLE001
            log.warning("startup.advisory_lock_unavailable", error=str(e))
            _init_lock = None

    Base.metadata.create_all(bind=engine)
    _run_schema_migrations()

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

    # Seed scraper registry from disk — loads all scraper_<domain>.py files that
    # exist in data/scrapers/ but are not yet in the DB (e.g. after a DB wipe
    # or on first boot with pre-written domain scrapers).
    from app.phase3_integration.scraper_registry import seed_from_disk
    seed_db = SessionLocal()
    try:
        seeded = seed_from_disk(seed_db)
        if seeded:
            write_audit("system.registry_seeded", f"Seeded {seeded} scraper(s) from disk into registry", level=INFO)
            log.info("vergabepilot.registry_seeded", count=seeded)
        else:
            log.info("vergabepilot.registry_seed_noop")
    except Exception as e:
        log.error("vergabepilot.registry_seed_failed", error=str(e))
    finally:
        seed_db.close()

    if _init_lock is not None:
        try:
            _init_lock.execute(_sa_text(f"SELECT pg_advisory_unlock({_STARTUP_LOCK_ID})"))
        finally:
            _init_lock.close()

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
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "X-Requested-With"],
)

# Dashboard payloads (audit trails, analytics) compress 5-10x.
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    # Only meaningful over TLS; the proxy sets X-Forwarded-Proto.
    if request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


# --- Global unhandled exception handler → writes to audit log ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    from fastapi import HTTPException as _HTTPException
    # Let FastAPI handle its own HTTP exceptions normally
    if isinstance(exc, _HTTPException):
        raise exc

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
    # Never expose internal error details or stack traces to clients
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# Routers
app.include_router(routes_jobs.router,       prefix="/api/jobs",       tags=["jobs"])
app.include_router(routes_scrapers.router,   prefix="/api/scrapers",   tags=["scrapers"])
app.include_router(routes_evaluation.router, prefix="/api/evaluation", tags=["phase1-evaluation"])
app.include_router(routes_agents.router,     prefix="/api/agents",     tags=["phase2-cua"])
app.include_router(routes_admin.router,      prefix="/api/admin",      tags=["admin"])
app.include_router(routes_audit.router,      prefix="/api/audit",      tags=["audit"])
app.include_router(routes_tests.router,      prefix="/api/tests",      tags=["tests"])
app.include_router(routes_extractor.router,  prefix="/api",            tags=["extraction"])
app.include_router(routes_directory.router,  prefix="/api/directory",  tags=["directory"])


@app.get("/")
def root():
    return {
        "service": "vergabepilot.ai",
        "version": "0.2.0",
        "phases": ["phase1_llm_scraper", "phase2_cua", "phase3_integration"],
        "docs": "/docs",
    }


@app.get("/metrics", include_in_schema=False)
def prometheus_metrics():
    """Prometheus-compatible metrics endpoint."""
    if not _metrics_module.is_available():
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(
            "# prometheus_client not installed\n", media_type="text/plain"
        )
    from fastapi.responses import Response
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST  # type: ignore
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


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


@app.get("/ready")
def ready():
    """
    Readiness probe — checks DB, Redis, and S3 connectivity.
    Returns 200 only when all dependencies are healthy.
    Used by load balancers and container orchestrators to route traffic.
    """
    from sqlalchemy import text
    checks: dict[str, str] = {}

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "error"

    try:
        import redis as _redis
        r = _redis.from_url(settings.redis_url, socket_connect_timeout=2)
        r.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={"status": "ready" if all_ok else "not_ready", "checks": checks},
    )
