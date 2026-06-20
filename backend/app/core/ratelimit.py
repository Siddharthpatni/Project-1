"""
Per-client rate limiting for public endpoints.

A small fixed-window limiter used to protect the unauthenticated tender-directory
API from scraping/abuse. Backed by Redis (shared across worker processes) with a
graceful in-process fallback when Redis is unavailable — mirrors the resilience
pattern of ``CircuitBreaker`` / ``DomainRateLimiter`` so a Redis blip degrades
rather than breaks (fail-open: a request is allowed if the limiter itself errors).

Usage — attach as a FastAPI dependency::

    limit = RateLimiter(times=60, seconds=60, scope="directory")

    @router.get("/things", dependencies=[Depends(limit)])
    def list_things(): ...

NOTE: this module deliberately does NOT use ``from __future__ import
annotations``. FastAPI must see the real ``Request`` class on ``__call__`` to
inject it; a stringized annotation on a class-instance dependency can't be
resolved (an instance has no ``__globals__``), so FastAPI would mistake
``request`` for a required query parameter and reject every call with HTTP 400.
"""
import threading
import time

from fastapi import HTTPException, Request

from app.config import settings
from app.core.metrics import RATE_LIMIT_HITS
from app.utils.logger import get_logger

log = get_logger(__name__)


def client_ip(request: Request) -> str:
    """Best-effort client IP. Honours the first X-Forwarded-For hop when the app
    runs behind a reverse proxy (its documented deployment); falls back to the
    socket peer. Spoofable, but acceptable for coarse rate limiting."""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


class RateLimiter:
    """Fixed-window limiter: at most ``times`` requests per ``seconds`` per key."""

    def __init__(self, times: int, seconds: int, scope: str) -> None:
        self.times = times
        self.seconds = seconds
        self.scope = scope
        self._redis: object | None = None
        self._redis_enabled = True
        # In-process fallback: key -> (window_start_epoch, count). Guarded by a
        # lock because the ASGI server may serve requests from multiple threads.
        self._local: dict[str, tuple[float, int]] = {}
        self._lock = threading.Lock()

    # -- redis ---------------------------------------------------------------
    def _get_redis(self):
        if not self._redis_enabled:
            return None
        if self._redis is None:
            try:
                import redis as _redis  # noqa: PLC0415

                self._redis = _redis.from_url(
                    settings.redis_url, decode_responses=True, socket_connect_timeout=2
                )
            except Exception:  # noqa: BLE001
                self._redis_enabled = False
                return None
        return self._redis

    # -- core decision -------------------------------------------------------
    def allow(self, key: str) -> bool:
        """Record a hit for ``key`` and return True if it is within the limit."""
        r = self._get_redis()
        if r is not None:
            try:
                full = f"ratelimit:{self.scope}:{key}"
                count = r.incr(full)
                if count == 1:
                    r.expire(full, self.seconds)
                return int(count) <= self.times
            except Exception:  # noqa: BLE001 — Redis down → fall back, don't fail
                self._redis_enabled = False
        return self._allow_local(key)

    def _allow_local(self, key: str) -> bool:
        now = time.time()
        with self._lock:
            window_start, count = self._local.get(key, (now, 0))
            if now - window_start >= self.seconds:
                window_start, count = now, 0
            count += 1
            self._local[key] = (window_start, count)
            # Opportunistic cleanup so the map can't grow without bound.
            if len(self._local) > 10_000:
                self._local = {
                    k: v for k, v in self._local.items() if now - v[0] < self.seconds
                }
        return count <= self.times

    # -- FastAPI dependency --------------------------------------------------
    async def __call__(self, request: Request) -> None:
        if not self.allow(client_ip(request)):
            RATE_LIMIT_HITS.inc()
            raise HTTPException(
                status_code=429,
                detail="Too many requests — please slow down and try again shortly.",
                headers={"Retry-After": str(self.seconds)},
            )
