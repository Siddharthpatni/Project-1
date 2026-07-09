"""robots.txt compliance — consulted once per origin before scraping.

Standard semantics: a missing, unreachable, or non-200 robots.txt means
crawling is allowed; only an explicit Disallow for our agent blocks a URL.
Fetch/parse problems never block the pipeline. Verdicts are cached per
origin for 24h. Disable globally with RESPECT_ROBOTS_TXT=false.
"""
from __future__ import annotations

import time
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from app.config import settings
from app.utils.logger import get_logger

log = get_logger(__name__)

USER_AGENT = "VergabepilotBot"
_TTL_SECONDS = 24 * 3600
# origin -> (fetched_at, parser or None when no policy applies)
_cache: dict[str, tuple[float, RobotFileParser | None]] = {}


async def robots_allows(url: str) -> bool:
    """True when robots.txt permits fetching *url* (or no policy exists)."""
    if not settings.respect_robots_txt:
        return True
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"

    cached = _cache.get(origin)
    if cached is None or time.time() - cached[0] > _TTL_SECONDS:
        parser: RobotFileParser | None = None
        try:
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                r = await client.get(f"{origin}/robots.txt")
            if r.status_code == 200:
                parser = RobotFileParser()
                parser.parse(r.text.splitlines())
        except Exception as e:
            log.debug("robots.fetch_failed", origin=origin, error=str(e)[:120])
        cached = (time.time(), parser)
        _cache[origin] = cached

    parser = cached[1]
    return True if parser is None else parser.can_fetch(USER_AGENT, url)
