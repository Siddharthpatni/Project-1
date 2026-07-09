"""Tests for the resilient HTTP helper (core/http_client.py).

A fake httpx.Client drives the retry logic deterministically; time.sleep is
patched out so the tests run instantly.
"""
from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from app.core import http_client as hc


class _Resp:
    def __init__(self, status_code, content=b"x", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class _FakeClient:
    """Returns queued responses or raises queued exceptions, in order."""

    def __init__(self, sequence):
        self._seq = list(sequence)
        self.calls = 0

    def request(self, method, url, **kwargs):
        self.calls += 1
        item = self._seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch.object(hc.time, "sleep", return_value=None):
        yield


def test_returns_immediately_on_success():
    client = _FakeClient([_Resp(200)])
    r = hc.get_with_retry(client, "https://x.test/a")
    assert r.status_code == 200
    assert client.calls == 1


def test_no_retry_on_404():
    """404 is deterministic — must not be retried."""
    client = _FakeClient([_Resp(404)])
    r = hc.get_with_retry(client, "https://x.test/missing")
    assert r.status_code == 404
    assert client.calls == 1


def test_retries_transient_status_then_succeeds():
    client = _FakeClient([_Resp(503), _Resp(502), _Resp(200)])
    with patch.object(hc.HTTP_RETRIES, "labels", return_value=hc.HTTP_RETRIES), \
         patch.object(hc.HTTP_RETRIES, "inc") as inc:
        r = hc.get_with_retry(client, "https://x.test/flaky", max_attempts=3)
    assert r.status_code == 200
    assert client.calls == 3
    assert inc.call_count == 2  # two retries before success


def test_returns_last_response_when_transient_exhausted():
    client = _FakeClient([_Resp(503), _Resp(503), _Resp(503)])
    r = hc.get_with_retry(client, "https://x.test/down", max_attempts=3)
    assert r.status_code == 503
    assert client.calls == 3


def test_retries_network_error_then_succeeds():
    client = _FakeClient([httpx.ConnectError("boom"), _Resp(200)])
    r = hc.get_with_retry(client, "https://x.test/net", max_attempts=3)
    assert r.status_code == 200
    assert client.calls == 2


def test_raises_when_network_error_exhausted():
    client = _FakeClient([httpx.TimeoutException("t"), httpx.TimeoutException("t")])
    with pytest.raises(httpx.TimeoutException):
        hc.get_with_retry(client, "https://x.test/timeout", max_attempts=2)
    assert client.calls == 2


def test_backoff_is_bounded_and_jittered():
    # base*2^(n-1) + jitter[0,base); attempt 1 -> [0.5,1.0), attempt 3 -> [2.0,2.5)
    d1 = hc._backoff_seconds(1, 0.5)
    d3 = hc._backoff_seconds(3, 0.5)
    assert 0.5 <= d1 < 1.0
    assert 2.0 <= d3 < 2.5
    # capped
    assert hc._backoff_seconds(20, 0.5, cap=8.0) < 8.0 + 0.5


def test_parse_retry_after():
    assert hc._parse_retry_after(_Resp(429, headers={"Retry-After": "3"})) == 3.0
    assert hc._parse_retry_after(_Resp(429, headers={"Retry-After": "999"})) == 10.0  # capped
    assert hc._parse_retry_after(_Resp(429)) is None
    assert hc._parse_retry_after(_Resp(429, headers={"Retry-After": "soon"})) is None
