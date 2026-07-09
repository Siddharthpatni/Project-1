"""Tests for the admin API key guard and robots.txt compliance layer."""
from __future__ import annotations

import asyncio
import time
from urllib.robotparser import RobotFileParser

import pytest
from fastapi import HTTPException

from app.api.routes_admin import require_admin_key
from app.config import settings
from app.core import robots
from app.core.security import classify_error
from app.phase3_integration.outcomes import BLOCKED, bucket_for


# ── Admin key guard ─────────────────────────────────────────────────────────

def test_admin_open_when_no_key_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "")
    require_admin_key(authorization=None, x_admin_key=None)  # no exception


def test_admin_rejects_missing_or_wrong_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "sekret")
    for auth, xkey in [(None, None), ("Bearer wrong", None), (None, "wrong")]:
        with pytest.raises(HTTPException) as exc:
            require_admin_key(authorization=auth, x_admin_key=xkey)
        assert exc.value.status_code == 403


def test_admin_accepts_key_via_either_header(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "sekret")
    require_admin_key(authorization="Bearer sekret", x_admin_key=None)
    require_admin_key(authorization=None, x_admin_key="sekret")


# ── robots.txt compliance ───────────────────────────────────────────────────

def _seed_policy(origin: str, lines: list[str] | None):
    parser = None
    if lines is not None:
        parser = RobotFileParser()
        parser.parse(lines)
    robots._cache[origin] = (time.time(), parser)


@pytest.fixture(autouse=True)
def _clean_cache():
    robots._cache.clear()
    yield
    robots._cache.clear()


def test_robots_disallow_blocks(monkeypatch):
    monkeypatch.setattr(settings, "respect_robots_txt", True)
    _seed_policy("https://x.test", ["User-agent: *", "Disallow: /private"])
    assert asyncio.run(robots.robots_allows("https://x.test/private/doc.pdf")) is False
    assert asyncio.run(robots.robots_allows("https://x.test/public/doc.pdf")) is True


def test_robots_absent_policy_allows(monkeypatch):
    monkeypatch.setattr(settings, "respect_robots_txt", True)
    _seed_policy("https://x.test", None)  # fetch found no robots.txt
    assert asyncio.run(robots.robots_allows("https://x.test/anything")) is True


def test_robots_fetch_failure_allows(monkeypatch):
    monkeypatch.setattr(settings, "respect_robots_txt", True)

    class _Boom:
        def __init__(self, **kw): ...
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): raise RuntimeError("network down")

    monkeypatch.setattr(robots.httpx, "AsyncClient", _Boom)
    assert asyncio.run(robots.robots_allows("https://down.test/page")) is True


def test_robots_disabled_by_setting(monkeypatch):
    monkeypatch.setattr(settings, "respect_robots_txt", False)
    _seed_policy("https://x.test", ["User-agent: *", "Disallow: /"])
    assert asyncio.run(robots.robots_allows("https://x.test/private")) is True


def test_robots_failure_taxonomy():
    assert classify_error("robots.txt disallows automated access") == "blocked_robots"
    assert bucket_for("blocked_robots") == BLOCKED
