"""
Structured logging setup using `structlog`.

Use it like:
    from app.utils.logger import get_logger
    log = get_logger(__name__)
    log.info("phase1.loop.iteration", url=url, iteration=i)
"""
from __future__ import annotations

import logging

import structlog

from app.config import settings


def _configure_once():
    if getattr(_configure_once, "_done", False):
        return
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.log_level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )
    _configure_once._done = True  # type: ignore[attr-defined]


def get_logger(name: str | None = None):
    _configure_once()
    return structlog.get_logger(name or __name__)


def bind_request_context(**kwargs) -> None:
    """Bind correlation fields (trace_id, job_id, item_id, domain, …) onto the
    current async context. Because `merge_contextvars` is in the processor
    chain, every subsequent log line in this context automatically carries
    them — giving an end-to-end, greppable trail for one URL's journey.

    None values are dropped so we don't clutter logs with empty keys.
    """
    _configure_once()
    clean = {k: v for k, v in kwargs.items() if v is not None}
    if clean:
        structlog.contextvars.bind_contextvars(**clean)


def clear_request_context() -> None:
    """Clear all bound correlation fields. Call in a `finally` per unit of work
    so context never leaks across items handled by the same worker."""
    structlog.contextvars.clear_contextvars()
