"""
FastAPI application entry point.

Wires up routers for all three phases plus admin endpoints, configures
CORS for the Next.js frontend, and exposes a health check.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    routes_agents,
    routes_admin,
    routes_evaluation,
    routes_jobs,
    routes_scrapers,
)
from app.config import settings
from app.database import Base, engine
from app.utils.logger import get_logger

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("vergabepilot.starting", version="0.1.0")
    Base.metadata.create_all(bind=engine)
    yield
    log.info("vergabepilot.shutdown")


app = FastAPI(
    title="Vergabepilot.AI",
    description=(
        "Agentic AI for Automated Public Project Scraping. "
        "Cascaded pipeline: existing scraper → LLM-generated scraper → CUA fallback."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers — one per resource / phase
app.include_router(routes_jobs.router,       prefix="/api/jobs",       tags=["jobs"])
app.include_router(routes_scrapers.router,   prefix="/api/scrapers",   tags=["scrapers"])
app.include_router(routes_evaluation.router, prefix="/api/evaluation", tags=["phase1-evaluation"])
app.include_router(routes_agents.router,     prefix="/api/agents",     tags=["phase2-cua"])
app.include_router(routes_admin.router,      prefix="/api/admin",      tags=["admin"])


@app.get("/")
def root():
    return {
        "service": "vergabepilot.ai",
        "version": "0.1.0",
        "phases": ["phase1_llm_scraper", "phase2_cua", "phase3_integration"],
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok"}
