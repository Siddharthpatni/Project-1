"""Tests for the public tender directory.

Covers the visibility rules (published + open only, expired hidden), grouping,
sorting (soonest-closing first), pagination, the public-field whitelist, empty
states, and the German deadline parser that feeds it.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import routes_directory as directory
from app.database import Base
from app.document_extractor.dates import parse_deadline
from app.models import Job, JobItem, JobStatus

# Far past / future so open-vs-expired is unambiguous regardless of the real clock.
PAST = datetime(2000, 1, 1, 12, 0, 0)
SOON = datetime(2099, 1, 1, 12, 0, 0)
LATER = datetime(2099, 6, 1, 12, 0, 0)
LATEST = datetime(2099, 12, 1, 12, 0, 0)


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Job(id="job-1", status=JobStatus.SUCCESS.value, total_urls=1))
    session.commit()
    try:
        yield session
    finally:
        session.close()


def _add(db, *, domain, status=JobStatus.SUCCESS.value, deadline=None,
         title="A tender", reference="REF-1") -> JobItem:
    item = JobItem(
        job_id="job-1",
        url=f"https://{domain}/tender/123",
        domain=domain,
        status=status,
        tender_title=title,
        tender_reference=reference,
        deadline=deadline,
        error_message="internal: boom",          # must never surface publicly
        attempts_detail=[{"strategy": "cua", "success": True}],
    )
    db.add(item)
    db.commit()
    return item


# ── domains listing ─────────────────────────────────────────────────────────

def test_domains_lists_only_those_with_open_tenders(db):
    _add(db, domain="open.de", deadline=SOON)
    _add(db, domain="expired.de", deadline=PAST)               # expired → hidden
    _add(db, domain="failed.de", status=JobStatus.FAILED.value)  # not published
    _add(db, domain="unknown.de", deadline=None)               # unknown → open

    domains = {d["domain"]: d["open_count"] for d in directory.list_directory_domains(db, seed=[])}

    assert domains == {"open.de": 1, "unknown.de": 1}
    assert "expired.de" not in domains
    assert "failed.de" not in domains


def test_open_count_excludes_expired_in_same_domain(db):
    _add(db, domain="mix.de", deadline=SOON)
    _add(db, domain="mix.de", deadline=LATER)
    _add(db, domain="mix.de", deadline=PAST)        # expired — not counted

    domains = {d["domain"]: d["open_count"] for d in directory.list_directory_domains(db, seed=[])}
    assert domains["mix.de"] == 2


def test_domains_sorted_busiest_first(db):
    _add(db, domain="one.de", deadline=SOON)
    for _ in range(3):
        _add(db, domain="three.de", deadline=SOON)

    result = [d["domain"] for d in directory.list_directory_domains(db, seed=[])]
    assert result == ["three.de", "one.de"]


def test_domain_carries_official_site_url(db):
    # _add stores url = https://<domain>/tender/123 → origin is the official portal.
    _add(db, domain="portal.de", deadline=SOON)
    assert directory.list_directory_domains(db, seed=[])[0]["site_url"] == "https://portal.de"


def test_seed_portals_listed_with_overlaid_counts(db):
    _add(db, domain="scraped.de", deadline=SOON)
    seed = [
        {"domain": "scraped.de", "site_url": "https://scraped.de"},
        {"domain": "never-scraped.de", "site_url": "https://never-scraped.de"},
    ]
    rows = directory.list_directory_domains(db, seed=seed)
    by = {d["domain"]: d for d in rows}
    # every seed portal appears; the scraped one carries its live count, the other 0
    assert by["scraped.de"]["open_count"] == 1
    assert by["never-scraped.de"]["open_count"] == 0
    assert by["never-scraped.de"]["site_url"] == "https://never-scraped.de"
    # portals with open tenders sort first
    assert [d["domain"] for d in rows] == ["scraped.de", "never-scraped.de"]


def test_domain_site_url_falls_back_to_https():
    assert directory._domain_site_url(None, "x.de") == "https://x.de"
    assert directory._domain_site_url("not a url", "x.de") == "https://x.de"
    assert directory._domain_site_url("http://x.de/a/b?c=1", "x.de") == "http://x.de"


# ── tenders within a domain ─────────────────────────────────────────────────

def test_tenders_sorted_soonest_first_unknown_last(db):
    _add(db, domain="x.de", deadline=LATER, reference="LATER")
    _add(db, domain="x.de", deadline=SOON, reference="SOON")
    _add(db, domain="x.de", deadline=None, reference="UNKNOWN")
    _add(db, domain="x.de", deadline=LATEST, reference="LATEST")

    refs = [t["reference"] for t in directory.list_domain_tenders(db, "x.de", 20, 0)["tenders"]]
    assert refs == ["SOON", "LATER", "LATEST", "UNKNOWN"]


def test_expired_tender_excluded_from_listing(db):
    _add(db, domain="x.de", deadline=SOON, reference="OPEN")
    _add(db, domain="x.de", deadline=PAST, reference="GONE")

    result = directory.list_domain_tenders(db, "x.de", 20, 0)
    assert result["total"] == 1
    assert [t["reference"] for t in result["tenders"]] == ["OPEN"]


def test_empty_domain_returns_empty_listing(db):
    _add(db, domain="x.de", deadline=PAST)   # only expired → domain has nothing open
    result = directory.list_domain_tenders(db, "x.de", 20, 0)
    assert result["total"] == 0
    assert result["tenders"] == []


def test_unknown_domain_returns_empty_listing(db):
    result = directory.list_domain_tenders(db, "does-not-exist.de", 20, 0)
    assert result == {
        "domain": "does-not-exist.de", "total": 0, "limit": 20, "offset": 0, "tenders": []
    }


def test_pagination(db):
    for i in range(5):
        # deadlines strictly increasing so order is deterministic
        _add(db, domain="x.de", deadline=datetime(2099, 1, i + 1), reference=f"R{i}")

    page = directory.list_domain_tenders(db, "x.de", limit=2, offset=2)
    assert page["total"] == 5
    assert [t["reference"] for t in page["tenders"]] == ["R2", "R3"]


def test_status_flags(db):
    from datetime import timedelta
    now = directory._now()
    _add(db, domain="x.de", deadline=now + timedelta(days=2), reference="SOON")
    _add(db, domain="x.de", deadline=now + timedelta(days=60), reference="OPEN")
    _add(db, domain="x.de", deadline=None, reference="UNK")

    by_ref = {t["reference"]: t["status"] for t in directory.list_domain_tenders(db, "x.de", 20, 0)["tenders"]}
    assert by_ref == {"SOON": "closing_soon", "OPEN": "open", "UNK": "deadline_unknown"}


def test_only_public_fields_exposed(db):
    _add(db, domain="x.de", deadline=SOON)
    tender = directory.list_domain_tenders(db, "x.de", 20, 0)["tenders"][0]

    assert set(tender.keys()) == {"job_id", "item_id", "title", "reference", "deadline", "status", "url"}
    # Internal columns must never leak.
    for leaked in ("error_message", "attempts_detail", "strategy", "failure_category", "iterations"):
        assert leaked not in tender


# ── German deadline parser ──────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("15.03.2024", datetime(2024, 3, 15, 23, 59, 59)),
    ("15.03.2024, 10:00 Uhr", datetime(2024, 3, 15, 10, 0, 0)),
    ("15/03/2024 09:30:15", datetime(2024, 3, 15, 9, 30, 15)),
    ("2024-03-15", datetime(2024, 3, 15, 23, 59, 59)),
    ("01.02.24", datetime(2024, 2, 1, 23, 59, 59)),
    ("Angebote bis 09.08.2026", datetime(2026, 8, 9, 23, 59, 59)),
])
def test_parse_deadline_valid(text, expected):
    assert parse_deadline(text) == expected


@pytest.mark.parametrize("text", ["", None, "kein Datum", "31.02.2024", "99.99.9999"])
def test_parse_deadline_invalid(text):
    assert parse_deadline(text) is None


# ── HTTP layer (regression for the rate-limiter dependency) ─────────────────

def test_endpoints_serve_200_through_dependency(db):
    """The rate-limit dependency must inject Request, not treat it as a required
    query param. Exercises the real FastAPI dependency wiring end-to-end."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.database import get_db

    _add(db, domain="open.de", deadline=SOON)

    app = FastAPI()
    app.include_router(directory.router, prefix="/api/directory")
    app.dependency_overrides[get_db] = lambda: db

    client = TestClient(app)

    r = client.get("/api/directory/domains")
    assert r.status_code == 200, r.text
    doms = r.json()["domains"]
    # the full 100-portal catalogue is always present, plus our scraped test domain
    assert len(doms) >= 100
    open_de = next(d for d in doms if d["domain"] == "open.de")
    assert open_de["open_count"] == 1 and open_de["site_url"] == "https://open.de"
    # a seed portal with no scraped tenders still appears, with count 0
    assert any(d["open_count"] == 0 for d in doms)

    r2 = client.get("/api/directory/domains/open.de/tenders")
    assert r2.status_code == 200, r2.text
    assert r2.json()["total"] == 1
