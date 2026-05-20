"""
Registry of reusable scrapers, keyed by domain.

On success in Phase 1, the generated code is promoted into this registry
so the next request for the same domain can skip code generation
entirely. Runtime statistics (success/failure counts) are tracked so we
can retire stale scrapers.

Generated scrapers are also written to disk under
`settings.scraper_registry_path` so a developer can read them and the
filesystem acts as a backup of the database.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ScraperTemplate
from app.utils.logger import get_logger

log = get_logger(__name__)


_DOMAIN_SAFE = re.compile(r"[^a-zA-Z0-9._-]")


def _safe_domain(domain: str) -> str:
    return _DOMAIN_SAFE.sub("_", domain) or "unknown"


def _registry_dir() -> Path:
    base = Path(settings.scraper_registry_path)
    try:
        base.mkdir(parents=True, exist_ok=True)
        # Quick write check
        probe = base / ".write_check"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        return base
    except OSError:
        # Fall back to system temp if the configured dir isn't writable.
        fallback = Path(tempfile.gettempdir()) / "vergabepilot-scrapers"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def get_for_domain(db: Session, domain: str) -> ScraperTemplate | None:
    return db.query(ScraperTemplate).filter(ScraperTemplate.domain == domain).first()


def upsert_from_generation(
    db: Session,
    domain: str,
    code: str,
    platform: str | None = None,
    route_used: bool = False,
) -> ScraperTemplate:
    tpl = get_for_domain(db, domain)
    if tpl is None:
        tpl = ScraperTemplate(
            domain=domain, code=code, source="llm",
            platform=platform, route_used=route_used,
        )
        db.add(tpl)
    else:
        tpl.code = code
        tpl.source = "llm"
        if platform is not None:
            tpl.platform = platform
        tpl.route_used = route_used
    db.commit()
    db.refresh(tpl)
    log.info("phase3.registry.upsert", domain=domain, platform=platform, route_used=route_used)

    # Best-effort disk mirror of the generated code.
    try:
        out_dir = _registry_dir()
        path = out_dir / f"scraper_{_safe_domain(domain)}.py"
        path.write_text(code, encoding="utf-8")
        log.info("phase3.registry.saved_to_disk", path=str(path))
    except Exception as e:  # noqa: BLE001
        log.warning("phase3.registry.disk_save_failed", error=str(e))

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
