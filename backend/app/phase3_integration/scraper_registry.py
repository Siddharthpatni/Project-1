"""
Registry of reusable scrapers, keyed by domain.

On success in Phase 1, the generated code is promoted into this registry
so the next request for the same domain can skip code generation
entirely. Runtime statistics (success/failure counts) are tracked so we
can retire stale scrapers.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ScraperTemplate
from app.utils.logger import get_logger

log = get_logger(__name__)


def get_for_domain(db: Session, domain: str) -> ScraperTemplate | None:
    return db.query(ScraperTemplate).filter(ScraperTemplate.domain == domain).first()


def upsert_from_generation(db: Session, domain: str, code: str) -> ScraperTemplate:
    tpl = get_for_domain(db, domain)
    if tpl is None:
        tpl = ScraperTemplate(domain=domain, code=code, source="llm")
        db.add(tpl)
    else:
        tpl.code = code
        tpl.source = "llm"
    db.commit()
    db.refresh(tpl)
    log.info("phase3.registry.upsert", domain=domain)
    return tpl


def record_outcome(db: Session, tpl: ScraperTemplate, success: bool, runtime: float) -> None:
    if success:
        tpl.success_count += 1
    else:
        tpl.failure_count += 1
    total = tpl.success_count + tpl.failure_count
    tpl.avg_runtime = ((tpl.avg_runtime * (total - 1)) + runtime) / max(total, 1)
    db.commit()


def should_retire(tpl: ScraperTemplate) -> bool:
    """Retire a scraper once its success rate drops below 20% over 10+ runs."""
    total = tpl.success_count + tpl.failure_count
    if total < 10:
        return False
    return (tpl.success_count / total) < 0.2
