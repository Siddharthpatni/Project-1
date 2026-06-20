"""
Universal adaptive scraper — a free, country/language-agnostic catch-all.

Most public procurement portals follow the same shape regardless of country:
a notice page with either direct document links, a single "download all" ZIP,
or a tab/section that reveals the documents after one click. This strategy
handles *any unknown domain* with that shape using multilingual heuristics — no
per-domain template, no LLM, no vision model.

It slots into the cascade as a free deterministic step **after DETERMINISTIC and
before the paid LLM generation**, so the many ordinary public portals are served
for free and the LLM budget is saved for the genuinely hard ones.

Flow (one bounded browser session, at most 1 click-hop):
  goto → harvest landing-page documents → if none, click the top multilingual
  document-nav candidates one hop and re-harvest → download via the live
  session's cookies, keeping only real documents.

When nothing is found, ``detect_wall`` inspects the page text to return a
precise reason (login_required / captcha / expired) so the failure is explained
rather than a generic "no documents". Never raises.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.core.browser_session import BrowserSession
from app.core.web_harvest import (
    detect_wall,
    download_documents,
    harvest_documents,
    rank_nav_candidates,
)
from app.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class AdaptiveResult:
    success: bool
    downloaded_files: list[str] = field(default_factory=list)
    error: str | None = None
    clicks: int = 0


# Reasons detect_wall can return → human-readable failure message. These line up
# with security.classify_error categories so the pipeline groups them correctly.
_WALL_MESSAGES = {
    "captcha": "captcha / bot-detection challenge — content gated",
    "login_required": "login required — documents behind a sign-in wall",
    "registration_required": "registration required — account needed for documents",
    "expired": "tender expired or archived — documents no longer available",
}


def run_adaptive(url: str, dest_dir: str, max_clicks: int = 3) -> AdaptiveResult:
    """Try to download documents from any portal using generic heuristics.

    Synchronous (sync Playwright) — the pipeline calls this via
    ``asyncio.to_thread``. Best-effort: returns a structured failure (never
    raises) so the cascade can fall through to LLM / CUA.
    """
    domain = urlparse(url).netloc

    try:
        with BrowserSession() as session:
            try:
                session.goto(url)  # also dismisses common cookie banners
            except Exception as e:  # noqa: BLE001
                return AdaptiveResult(False, error=f"page load failed: {e}")

            cookies = _cookies(session)

            # 1) Documents already on the landing page?
            links = harvest_documents(session)
            if links:
                saved = download_documents(links, dest_dir, cookies)
                if saved:
                    log.info("adaptive.landing_success", url=url, docs=len(saved))
                    return AdaptiveResult(True, saved)

            # 2) Click the most promising document-nav candidates, one hop each.
            clicks = 0
            for cand in rank_nav_candidates(session, domain, limit=max_clicks):
                text = cand.get("text")
                if not text:
                    continue
                try:
                    session.click_text(text, wait_ms=3000)
                    clicks += 1
                except Exception:  # noqa: BLE001
                    continue
                links = harvest_documents(session)
                if not links:
                    continue
                # refresh cookies in case the click established a session
                saved = download_documents(links, dest_dir, _cookies(session) or cookies)
                if saved:
                    log.info("adaptive.click_success", url=url, click=text[:60], docs=len(saved))
                    return AdaptiveResult(True, saved, clicks=clicks)

            # 3) Nothing found — explain why if the page is gated.
            reason = _diagnose(session)
            log.info("adaptive.no_documents", url=url, reason=reason, clicks=clicks)
            return AdaptiveResult(False, error=reason, clicks=clicks)

    except Exception as e:  # noqa: BLE001
        log.warning("adaptive.unexpected_error", url=url, error=str(e))
        return AdaptiveResult(False, error=f"adaptive scraper error: {e}")


def _cookies(session) -> list[dict]:
    try:
        return session.page.context.cookies()
    except Exception:  # noqa: BLE001
        return []


def _diagnose(session) -> str:
    """Turn a no-document outcome into a precise, human-readable reason."""
    try:
        text = session.content()
    except Exception:  # noqa: BLE001
        text = ""
    wall = detect_wall(text)
    if wall:
        return _WALL_MESSAGES.get(wall, wall)
    return "no downloadable documents found"
