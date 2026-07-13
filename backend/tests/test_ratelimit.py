"""Tests for the public-endpoint rate limiter (in-process fallback path)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.ratelimit import RateLimiter, client_ip


def _local_limiter(times: int, seconds: int = 60) -> RateLimiter:
    rl = RateLimiter(times=times, seconds=seconds, scope="test")
    rl._redis_enabled = False  # force the in-process fallback (no Redis in tests)
    return rl


def test_allows_up_to_limit_then_blocks():
    rl = _local_limiter(times=3)
    assert [rl.allow("1.2.3.4") for _ in range(4)] == [True, True, True, False]


def test_keys_are_independent():
    rl = _local_limiter(times=1)
    assert rl.allow("a") is True
    assert rl.allow("b") is True      # different IP → its own budget
    assert rl.allow("a") is False


def test_window_resets_after_elapsed():
    rl = _local_limiter(times=1, seconds=60)
    assert rl.allow("ip") is True
    assert rl.allow("ip") is False
    # Simulate the fixed window elapsing.
    start, count = rl._local["ip"]
    rl._local["ip"] = (start - 61, count)
    assert rl.allow("ip") is True


def test_dependency_raises_429_when_over_limit():
    rl = _local_limiter(times=1)
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="9.9.9.9"))
    asyncio.run(rl(req))              # first request within budget
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(rl(req))
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers["Retry-After"] == "60"


def test_client_ip_prefers_forwarded_for():
    req = SimpleNamespace(
        headers={"X-Forwarded-For": "1.1.1.1, 2.2.2.2"},
        client=SimpleNamespace(host="3.3.3.3"),
    )
    assert client_ip(req) == "1.1.1.1"


def test_client_ip_falls_back_to_peer():
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="3.3.3.3"))
    assert client_ip(req) == "3.3.3.3"
