"""
Scraper-template management (the Phase-3 registry of reusable scrapers).

GET    /api/scrapers          → list templates
POST   /api/scrapers          → add a manually-written template
GET    /api/scrapers/{domain} → retrieve code for a given domain
DELETE /api/scrapers/{id}     → remove template

POST   /api/scrapers/learn    → learn the navigation route for a URL,
                                then ask the LLM to generate a
                                deterministic scraper that follows it.
"""
from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.core.llm_client import LLMClient
from app.core.security import is_url_allowed
from app.database import get_db
from app.models import ScraperTemplate
from app.phase1_llm_scraper.generator import ScraperGenerator
from app.phase1_llm_scraper.route_learner import learn_route
from app.phase1_llm_scraper.validator import validate
from app.phase3_integration import platform_classifier, scraper_registry
from app.schemas import (
    LearnRouteRequest,
    LearnRouteResponse,
    RouteMapRead,
    ScraperTemplateCreate,
    ScraperTemplateRead,
)
from app.utils.logger import get_logger

router = APIRouter()
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[ScraperTemplateRead])
def list_scrapers(db: Session = Depends(get_db)):
    return db.query(ScraperTemplate).order_by(ScraperTemplate.updated_at.desc()).all()


@router.post("", response_model=ScraperTemplateRead, status_code=201)
def create_scraper(payload: ScraperTemplateCreate, db: Session = Depends(get_db)):
    existing = db.query(ScraperTemplate).filter(ScraperTemplate.domain == payload.domain).first()
    if existing:
        raise HTTPException(409, f"scraper for domain {payload.domain} already exists")

    tpl = ScraperTemplate(
        domain=payload.domain,
        code=payload.code,
        language=payload.language,
        source=payload.source,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.get("/{domain}", response_model=ScraperTemplateRead)
def get_scraper(domain: str, db: Session = Depends(get_db)):
    tpl = db.query(ScraperTemplate).filter(ScraperTemplate.domain == domain).first()
    if not tpl:
        raise HTTPException(404, "scraper not found")
    return tpl


@router.delete("/{scraper_id}", status_code=204)
def delete_scraper(scraper_id: str, db: Session = Depends(get_db)):
    tpl = db.query(ScraperTemplate).filter(ScraperTemplate.id == scraper_id).first()
    if not tpl:
        raise HTTPException(404, "scraper not found")
    db.delete(tpl)
    db.commit()


# ---------------------------------------------------------------------------
# Route-learning + generation
# ---------------------------------------------------------------------------

@router.post("/learn", response_model=LearnRouteResponse)
async def learn_and_generate(payload: LearnRouteRequest, db: Session = Depends(get_db)):
    """
    Visit `url` with a real browser, trace the click path to documents,
    classify the platform, and (optionally) ask the LLM to generate a
    scraper that follows the discovered route.

    Synchronous: the request blocks until learning + generation finish
    (typically 10-60 seconds depending on the site). Clients that need
    a fire-and-forget version should call this from a background task.
    """
    url_str = str(payload.url)
    allowed, reason = is_url_allowed(url_str)
    if not allowed:
        raise HTTPException(400, f"url not allowed: {reason}")

    domain = urlparse(url_str).netloc
    platform = platform_classifier.classify_url(url_str)
    max_clicks = payload.max_clicks or settings.route_learning_max_clicks

    # 1. Learn the route — Playwright is sync, so run in a worker thread.
    log.info("api.scrapers.learn.start", url=url_str, platform=platform)
    route_map = await asyncio.to_thread(learn_route, url_str, max_clicks)

    response = LearnRouteResponse(
        domain=domain,
        platform=platform,
        route_map=RouteMapRead(**route_map.to_dict()),
        documents_found=route_map.total_documents_found,
        status="route_learned" if route_map.learned else "no_route_found",
    )

    if not payload.generate_scraper:
        return response

    if not route_map.learned:
        # Still return the (empty) route map so the client can show it,
        # but skip generation — no point asking the LLM to follow nothing.
        response.status = "no_route_found"
        return response

    # 2. Generate a scraper guided by the learned route.
    llm = LLMClient(default_model=payload.model)
    generator = ScraperGenerator(llm)
    try:
        scraper = await generator.generate(
            url=url_str,
            model=payload.model,
            route_map=route_map,
            platform=platform if platform != "unknown" else None,
        )
    except Exception as e:  # noqa: BLE001
        log.exception("api.scrapers.learn.generate_failed")
        response.status = f"generation_failed: {e}"
        return response

    # 3. Validate before we let anyone run it.
    v = validate(scraper.code)
    if not v.ok:
        response.scraper_code = scraper.code
        response.cost_usd = scraper.cost_usd
        response.status = f"generated_but_invalid: {'; '.join(v.errors)}"
        return response

    # 4. Persist into the registry so the next request for this domain
    #    skips both route-learning and generation entirely.
    tpl = scraper_registry.upsert_from_generation(
        db=db, domain=domain, code=scraper.code,
        platform=platform if platform != "unknown" else None,
        route_used=True,
    )

    response.scraper_code = scraper.code
    response.scraper_id = tpl.id
    response.cost_usd = scraper.cost_usd
    response.status = "generated_and_saved"
    return response
