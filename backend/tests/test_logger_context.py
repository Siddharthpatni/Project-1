"""Tests for correlation-context helpers (utils/logger.py)."""
from __future__ import annotations

import structlog

from app.utils.logger import bind_request_context, clear_request_context


def teardown_function():
    clear_request_context()


def test_bind_and_clear_request_context():
    clear_request_context()
    bind_request_context(trace_id="job1:item1", job_id="job1", item_id="item1", domain="x.test")
    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("trace_id") == "job1:item1"
    assert ctx.get("job_id") == "job1"
    assert ctx.get("domain") == "x.test"

    clear_request_context()
    assert structlog.contextvars.get_contextvars() == {}


def test_bind_drops_none_values():
    clear_request_context()
    bind_request_context(trace_id="t", job_id=None, domain=None)
    ctx = structlog.contextvars.get_contextvars()
    assert ctx.get("trace_id") == "t"
    assert "job_id" not in ctx
    assert "domain" not in ctx
