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
    tpl = db.query(ScraperTemplate).filter(ScraperTemplate.domain == domain).first()
    if tpl is not None:
        return tpl

    # Filesystem fallback: a scraper file on disk not yet in DB (e.g. after a
    # DB wipe or fresh container startup before seed_from_disk ran).
    safe = _safe_domain(domain)
    path = _registry_dir() / f"scraper_{safe}.py"
    if not path.is_file():
        return None

    try:
        code = path.read_text(encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.warning("phase3.registry.fs_fallback_read_failed", domain=domain, error=str(e))
        return None

    # Guard against concurrent workers both finding no DB row and both trying
    # to INSERT — the second one gets an IntegrityError on the unique domain
    # constraint. Handle it by re-querying instead of crashing.
    from sqlalchemy.exc import IntegrityError
    try:
        tpl = ScraperTemplate(domain=domain, code=code, source="disk", platform=None, route_used=False)
        db.add(tpl)
        db.commit()
        db.refresh(tpl)
        log.info("phase3.registry.fs_fallback_loaded", domain=domain, path=str(path))
        return tpl
    except IntegrityError:
        db.rollback()
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


def store_cua_hint(db: Session, domain: str, hint: str) -> None:
    """Persist CUA interaction knowledge for a domain.

    Called after every CUA attempt (success or failure) so future LLM
    generation passes can use the verified navigation trace as context.
    Creates a minimal ScraperTemplate stub if none exists yet.
    """
    tpl = db.query(ScraperTemplate).filter(ScraperTemplate.domain == domain).first()
    if tpl is None:
        tpl = ScraperTemplate(
            domain=domain,
            code="# placeholder — CUA ran before LLM generation",
            source="cua",
        )
        db.add(tpl)
    tpl.cua_hint = hint[:8000]  # cap to avoid massive DB rows
    db.commit()
    log.info("phase3.registry.cua_hint_stored", domain=domain, hint_len=len(hint))


def store_learned_route(db: Session, domain: str, route) -> None:
    """Persist a replayable navigation route learned from a CUA-only success.

    Called by the CUA route learner after the agent reached the documents when
    every cheaper strategy failed. Creates a minimal stub row if the domain has
    no template yet (mirrors store_cua_hint). ``route`` is a LearnedRoute.
    """
    tpl = db.query(ScraperTemplate).filter(ScraperTemplate.domain == domain).first()
    if tpl is None:
        tpl = ScraperTemplate(
            domain=domain,
            code="# placeholder — CUA route learned before any scraper existed",
            source="cua",
        )
        db.add(tpl)
    tpl.learned_route = route.to_dict()
    db.commit()
    log.info(
        "phase3.registry.learned_route_stored",
        domain=domain, steps=len(route.steps), docs=len(route.document_links),
    )


def get_learned_route(db: Session, domain: str):
    """Return the stored LearnedRoute for a domain, or None.

    Returns None when no row exists or the column is empty/malformed — the
    caller (LEARNED_ROUTE strategy) then fast-fails and the cascade continues.
    """
    from app.phase2_cua.route_learner import LearnedRoute  # noqa: PLC0415

    tpl = db.query(ScraperTemplate).filter(ScraperTemplate.domain == domain).first()
    if tpl is None or not tpl.learned_route:
        return None
    return LearnedRoute.from_dict(tpl.learned_route)


def seed_from_disk(db: Session) -> int:
    """Load all scraper_<domain>.py files from the registry directory into the DB.

    Called once at startup. Only inserts entries that are not already in the DB —
    never overwrites existing records so live statistics are preserved.

    Returns the count of newly seeded entries.
    """
    reg_dir = _registry_dir()
    seeded = 0
    for path in sorted(reg_dir.glob("scraper_*.py")):
        # Filename is scraper_{safe_domain}.py.  Since valid domain characters
        # ([a-zA-Z0-9.-]) are all preserved by _safe_domain(), the stem after
        # stripping the prefix equals the original domain.
        domain = path.stem[len("scraper_"):]
        if not domain:
            continue

        existing = db.query(ScraperTemplate).filter(ScraperTemplate.domain == domain).first()

        try:
            code = path.read_text(encoding="utf-8")
        except Exception as e:  # noqa: BLE001
            log.warning("phase3.registry.seed_read_failed", path=str(path), error=str(e))
            continue

        if existing is not None:
            # Overwrite only if the DB entry was LLM/CUA generated — disk scrapers are
            # manually written and therefore more reliable than auto-generated code.
            # Never overwrite a previously-successful "disk" or "manual" entry.
            if existing.source not in ("disk", "manual"):
                existing.code   = code
                existing.source = "disk"
                seeded += 1
                log.info("phase3.registry.upgraded_from_disk", domain=domain, was=existing.source)
            continue

        tpl = ScraperTemplate(domain=domain, code=code, source="disk", platform=None, route_used=False)
        db.add(tpl)
        seeded += 1
        log.info("phase3.registry.seeded_from_disk", domain=domain, path=str(path))

    if seeded:
        db.commit()

    return seeded
