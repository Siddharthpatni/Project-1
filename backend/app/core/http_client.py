"""
Resilient outbound HTTP — retry with exponential backoff + jitter.

German and international procurement portals are frequently flaky (slow TLS,
transient 502/503 behind load balancers, brief connection resets). A single
attempt throws away winnable downloads. This helper wraps an existing
``httpx.Client`` with bounded retries on *transient* failures only —
never on deterministic ones (404/401/400), so we don't waste time or hammer a
portal that is genuinely refusing us.

Synchronous by design: the document-download paths (web_harvest, replay) run in
worker threads via ``asyncio.to_thread``. The async LLM client in
``core.llm_client`` has its own tuned retry policy and is intentionally not
routed through here.
"""
from __future__ import annotations

import random
import time

import httpx

from app.core.metrics import HTTP_RETRIES
from app.utils.logger import get_logger

log = get_logger(__name__)

# Status codes worth retrying — transient server/throttling conditions.
TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Exceptions worth retrying — transient network/transport conditions.
_RETRYABLE_EXC = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
    httpx.PoolTimeout,
)


def _backoff_seconds(attempt: int, base_delay: float, cap: float = 8.0) -> float:
    """Exponential backoff with full jitter: base*2^(n-1), capped, + random[0,base)."""
    expo = min(cap, base_delay * (2 ** (attempt - 1)))
    return expo + random.uniform(0, base_delay)


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    max_attempts: int = 3,
    base_delay: float = 0.5,
    **kwargs,
) -> httpx.Response:
    """Issue an HTTP request, retrying transient failures with backoff.

    Returns the final ``httpx.Response`` (which may still carry a transient
    status if all attempts were exhausted — the caller checks ``status_code``).
    Raises the last transport exception only when every attempt failed at the
    network level. Increments the HTTP_RETRIES metric per retry.
    """
    last_resp: httpx.Response | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.request(method, url, **kwargs)
        except _RETRYABLE_EXC as e:
            if attempt >= max_attempts:
                raise
            HTTP_RETRIES.labels(reason="network").inc()
            log.warning("http.retry_network", url=url[:200], attempt=attempt,
                        reason=type(e).__name__)
            time.sleep(_backoff_seconds(attempt, base_delay))
            continue

        if resp.status_code in TRANSIENT_STATUS and attempt < max_attempts:
            HTTP_RETRIES.labels(reason=f"status_{resp.status_code}").inc()
            log.warning("http.retry_status", url=url[:200], attempt=attempt,
                        status=resp.status_code)
            last_resp = resp
            # Honour Retry-After when the server provides it (cap to backoff window).
            retry_after = _parse_retry_after(resp)
            time.sleep(retry_after if retry_after is not None else _backoff_seconds(attempt, base_delay))
            continue

        return resp

    # All attempts exhausted on a transient status — return the last response so
    # the caller can inspect it rather than crashing.
    assert last_resp is not None  # loop guarantees this when we reach here
    return last_resp


def get_with_retry(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """Convenience wrapper for GET requests."""
    return request_with_retry(client, "GET", url, **kwargs)


def _parse_retry_after(resp: httpx.Response) -> float | None:
    """Parse a numeric Retry-After header (seconds), capped at 10s. None if absent/invalid."""
    val = resp.headers.get("Retry-After")
    if not val:
        return None
    try:
        return min(10.0, float(val))
    except (TypeError, ValueError):
        return None
