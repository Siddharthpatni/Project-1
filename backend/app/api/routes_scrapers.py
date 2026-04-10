"""
Scraper-template management (the Phase-3 registry of reusable scrapers).

GET    /api/scrapers          → list templates
POST   /api/scrapers          → add a manually-written template
GET    /api/scrapers/{domain} → retrieve code for a given domain
DELETE /api/scrapers/{id}     → remove template
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ScraperTemplate
from app.schemas import ScraperTemplateCreate, ScraperTemplateRead

router = APIRouter()


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
