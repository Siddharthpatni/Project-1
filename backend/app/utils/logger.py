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
