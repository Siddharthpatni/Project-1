"""
Public tender directory — browse open tenders by domain (no authentication).

This is a read-only, public-facing view over the data the pipeline already has:
a successful ``JobItem`` is one published tender, grouped by its ``domain``. It
deliberately exposes only a whitelist of public, tender-facing fields (title,
reference, deadline, status, source URL, and the IDs needed to link to the
existing detail page) — never internal columns such as error messages, cascade
attempt traces, costs, or strategy internals.

Visibility rules
────────────────
A tender is shown only when it is **published and currently open**:
  * published  → JobItem.status == SUCCESS (it was successfully scraped)
  * open       → deadline is in the future, OR unknown (NULL). A deadline in the
                 past marks the tender expired and hides it.

Endpoints (mounted at /api/directory; all per-IP rate limited)
  GET /domains                       → domains that have ≥1 open tender + counts
  GET /domains/{domain}/tenders      → paginated open tenders in a domain,
                                       soonest-closing first
"""
from __future__ import annotations

from datetime import datetime, UTC
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.core.ratelimit import RateLimiter
from app.database import get_db
from app.models import JobItem, JobStatus
from app.phase3_integration.portal_directory_seed import PORTAL_DOMAINS

# Per-IP limiter shared by every public directory endpoint.
directory_limit = RateLimiter(
    times=settings.public_rate_limit_per_minute, seconds=60, scope="directory"
)

router = APIRouter(dependencies=[Depends(directory_limit)])

# Tenders closing within this many days are flagged "closing_soon" in the UI.
_CLOSING_SOON_DAYS = 7


def _now() -> datetime:
    """Naive UTC 'now', matching the naive datetimes stored in JobItem.deadline."""
    return datetime.now(UTC).replace(tzinfo=None)


def _open_conditions(now: datetime):
    """SQLAlchemy conditions for a published, currently-open tender."""
    return [
        JobItem.status == JobStatus.SUCCESS.value,
        or_(JobItem.deadline.is_(None), JobItem.deadline >= now),
    ]


def _domain_site_url(sample_url: str | None, domain: str) -> str:
    """Link to the domain's official portal: the origin (scheme://host) of a real
    tender URL we hold — so the scheme is correct — falling back to https://<domain>."""
    try:
        parsed = urlparse(sample_url or "")
        if parsed.scheme in ("http", "https") and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:  # noqa: BLE001
        pass
    return f"https://{domain}"


def list_directory_domains(db: Session, seed: list[dict] | None = None) -> list[dict]:
    """Every known procurement portal (the seed list) plus any other domain we've
    scraped, each with a link to its official site and a live open-tender count.

    Domains that currently have open tenders are surfaced first, then the rest
    alphabetically. ``seed`` defaults to the full PORTAL_DOMAINS catalogue;
    tests pass a small one (or ``[]``) to isolate the scraped-data logic.
    """
    portals = PORTAL_DOMAINS if seed is None else seed
    now = _now()

    counts: dict[str, int] = dict(
        db.query(JobItem.domain, func.count(JobItem.id))
        .filter(*_open_conditions(now))
        .filter(JobItem.domain.isnot(None), JobItem.domain != "")
        .group_by(JobItem.domain)
        .all()
    )

    out: dict[str, dict] = {}
    for p in portals:
        dom = p["domain"]
        out[dom] = {"domain": dom, "open_count": int(counts.get(dom, 0)), "site_url": p["site_url"]}

    # Scraped domains not in the seed catalogue — surface them too, with a
    # site_url derived from one of their real tender URLs.
    extra = [d for d in counts if d not in out]
    if extra:
        samples: dict[str, str] = dict(
            db.query(JobItem.domain, func.min(JobItem.url))
            .filter(JobItem.domain.in_(extra))
            .group_by(JobItem.domain)
            .all()
        )
        for dom in extra:
            out[dom] = {
                "domain": dom,
                "open_count": int(counts[dom]),
                "site_url": _domain_site_url(samples.get(dom), dom),
            }

    result = list(out.values())
    result.sort(key=lambda r: (-r["open_count"], r["domain"]))
    return result


def _tender_status(deadline: datetime | None, now: datetime) -> str:
    if deadline is None:
        return "deadline_unknown"
    if (deadline - now).days < _CLOSING_SOON_DAYS:
        return "closing_soon"
    return "open"


def _public_tender(item: JobItem, now: datetime) -> dict:
    """Whitelist of public, tender-facing fields — nothing internal leaks out."""
    return {
        "job_id":    item.job_id,
        "item_id":   item.id,
        "title":     item.tender_title,
        "reference": item.tender_reference,
        "deadline":  item.deadline.isoformat() if item.deadline else None,
        "status":    _tender_status(item.deadline, now),
        "url":       item.url,
    }


def list_domain_tenders(db: Session, domain: str, limit: int, offset: int) -> dict:
    """Paginated open tenders for one domain, soonest-closing first.

    Ordering: known deadlines ascending (soonest first), unknown-deadline tenders
    last. Works the same on SQLite and Postgres (explicit NULLs-last expression).
    """
    now = _now()
    base = db.query(JobItem).filter(*_open_conditions(now), JobItem.domain == domain)

    total = base.count()
    items = (
        base.order_by(
            JobItem.deadline.is_(None),     # False (0) → real deadlines first
            JobItem.deadline.asc(),
            JobItem.id.asc(),               # stable tiebreak for pagination
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "domain":  domain,
        "total":   total,
        "limit":   limit,
        "offset":  offset,
        "tenders": [_public_tender(it, now) for it in items],
    }


@router.get("/domains")
def get_domains(db: Session = Depends(get_db)):
    """Every procurement portal in the directory, with a live open-tender count."""
    return {"domains": list_directory_domains(db)}


@router.get("/domains/{domain}/tenders")
def get_domain_tenders(
    domain: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Paginated list of open tenders in a domain, soonest-closing first."""
    return list_domain_tenders(db, domain, limit, offset)
