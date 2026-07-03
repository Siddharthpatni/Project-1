"""
CUA Route Learner — turn a one-time CUA success into a permanent cheap path.

When the computer-use agent (Phase 2) is the *only* strategy that manages to
reach a portal's documents (everything cheaper — existing scraper, deterministic
template, LLM generation — has failed), it is wasteful to pay the full CUA cost
(~30-120s + vision-LLM tokens) on every future visit to that same domain.

This module captures a **replayable navigation route** immediately after such a
success and lets the pipeline replay it later with a cheap headless Playwright
pass — no LLM, no vision model, no full agent loop.

Two halves:
  * ``learn_from_cua(url, outcome)`` — runs the proven heuristic tracer
    (``phase1_llm_scraper.route_learner.learn_route``) to record the click path
    + document links, falling back to any direct document URLs the CUA itself
    discovered. Returns a ``LearnedRoute`` or ``None`` when nothing replayable
    could be captured (e.g. a true login wall — keep using CUA there).
  * ``replay(route, dest_dir)`` — re-walks the recorded steps with a
    ``BrowserSession`` and downloads the documents into ``dest_dir`` using the
    live browser's cookies. Best-effort: never raises, returns ``[]`` on a miss
    so the cascade simply falls through to CUA again.

Persistence (the ``ScraperTemplate.learned_route`` column + registry helpers)
lives in ``phase3_integration.scraper_registry``.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.core.browser_session import BrowserSession
from app.core.web_harvest import DOC_SUFFIXES as _DOC_SUFFIXES
from app.core.web_harvest import download_documents, harvest_documents
from app.utils.logger import get_logger

log = get_logger(__name__)

# Matches absolute http(s) URLs (used to salvage doc links out of CUA trace text).
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)


@dataclass
class LearnedRoute:
    """A replayable navigation route captured from a CUA-only success.

    Stored as JSON in ``ScraperTemplate.learned_route``. ``steps`` is a flat
    list of plain dicts (``{"action", "selector", "text", "url"}``) so it
    serializes/deserializes without any custom machinery.
    """
    domain: str
    start_url: str
    steps: list[dict] = field(default_factory=list)
    document_links: list[str] = field(default_factory=list)
    learned_via: str = "cua"
    confidence: float = 0.0
    learned_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict | None) -> "LearnedRoute | None":
        if not d:
            return None
        try:
            return cls(
                domain=d.get("domain", ""),
                start_url=d.get("start_url", ""),
                steps=list(d.get("steps") or []),
                document_links=list(d.get("document_links") or []),
                learned_via=d.get("learned_via", "cua"),
                confidence=float(d.get("confidence", 0.0)),
                learned_at=d.get("learned_at", ""),
            )
        except Exception:  # noqa: BLE001 — never let a malformed row break the cascade
            return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Portals commonly serve documents from suffix-less endpoints
# (/download?id=…, GetDocumentFile, …) — suffix matching alone missed them all.
_DOWNLOADISH_RE = re.compile(
    r"download|getdocument|documentfile|getfile|attachment|docid=|unterlagen",
    re.IGNORECASE,
)


def _is_document_url(url: str) -> bool:
    if not url:
        return False
    low = url.lower().split("?", 1)[0]
    if low.endswith(_DOC_SUFFIXES):
        return True
    return bool(_DOWNLOADISH_RE.search(url))


def _salvage_links_from_outcome(outcome) -> list[str]:
    """Best-effort: pull direct document URLs out of a CUA outcome.

    The CUA trace stores raw state strings (not structured selectors), so we
    can only reliably recover *direct* document URLs that appear in the text or
    in the list of files the agent actually downloaded.
    """
    found: list[str] = []

    def _add(url: str) -> None:
        if _is_document_url(url) and url not in found:
            found.append(url)

    for f in getattr(outcome, "downloaded_files", None) or []:
        # downloaded_files are local paths after a run; only useful if the agent
        # recorded a remote URL — skip local paths, keep any http(s) entries.
        if isinstance(f, str) and f.lower().startswith(("http://", "https://")):
            _add(f)

    for step in getattr(outcome, "trace", None) or []:
        text = ""
        if isinstance(step, dict):
            text = str(step.get("state") or step.get("description") or step.get("url") or "")
        else:
            text = str(step)
        for m in _URL_RE.findall(text):
            _add(m)

    return found


def _salvage_page_urls_from_outcome(outcome, domain: str) -> list[str]:
    """Same-domain page URLs from the CUA trace, in visit order.

    The agent's raw state strings record where it navigated. The deepest page
    it reached is where the documents were — replaying a plain goto there and
    re-harvesting is often all a replay needs.
    """
    pages: list[str] = []
    for step in getattr(outcome, "trace", None) or []:
        text = str(step.get("state") or step.get("description") or step.get("url") or "") \
            if isinstance(step, dict) else str(step)
        for m in _URL_RE.findall(text):
            cleaned = m.rstrip(".,;")
            host = urlparse(cleaned).netloc
            if host != domain or _is_document_url(cleaned):
                continue
            if cleaned not in pages:
                pages.append(cleaned)
    return pages


def learn_from_cua(url: str, outcome) -> LearnedRoute | None:
    """Capture a replayable route after the CUA succeeded on ``url``.

    Synchronous (uses sync Playwright via ``learn_route``) — the pipeline calls
    this inside ``asyncio.to_thread``. Returns ``None`` when no replayable route
    could be captured, in which case the caller keeps relying on the CUA.
    """
    domain = urlparse(url).netloc

    # 1) Try the proven heuristic tracer — it yields a clean, structured click
    #    path plus the document links, exactly what we want to replay.
    try:
        from app.phase1_llm_scraper.route_learner import learn_route  # noqa: PLC0415
        rm = learn_route(url)
    except Exception as e:  # noqa: BLE001
        log.warning("cua_route_learner.trace_failed", url=url, error=str(e))
        rm = None

    if rm is not None and rm.learned and rm.document_links:
        steps: list[dict] = []
        for s in rm.steps:
            if s.action not in ("goto", "click"):
                continue
            steps.append({
                "action": s.action,
                "selector": s.selector,
                "text": s.text,
                "url": s.url,
            })
        route = LearnedRoute(
            domain=domain,
            start_url=url,
            steps=steps or [{"action": "goto", "selector": None, "text": None, "url": url}],
            document_links=list(rm.document_links),
            learned_via="cua+trace",
            confidence=min(1.0, rm.total_documents_found / 3.0),
            learned_at=_now_iso(),
        )
        log.info(
            "cua_route_learner.learned",
            url=url, steps=len(route.steps), docs=len(route.document_links),
        )
        return route

    # 2) Fallback: salvage direct document URLs the CUA itself surfaced.
    salvaged = _salvage_links_from_outcome(outcome)
    if salvaged:
        route = LearnedRoute(
            domain=domain,
            start_url=url,
            steps=[{"action": "goto", "selector": None, "text": None, "url": url}],
            document_links=salvaged,
            learned_via="cua_links",
            confidence=0.3,
            learned_at=_now_iso(),
        )
        log.info("cua_route_learner.learned_links_only", url=url, docs=len(salvaged))
        return route

    # 3) Last resort: replay a goto to the deepest same-domain page the agent
    # reached and re-harvest there. Before this fallback existed the learner
    # returned None for most CUA wins (the fresh unauthenticated re-trace in
    # step 1 fails on exactly the portals only the CUA could crack), so the
    # LEARNED_ROUTE strategy never had anything to replay.
    pages = _salvage_page_urls_from_outcome(outcome, domain)
    final_page = pages[-1] if pages else None
    if final_page and final_page.rstrip("/") != url.rstrip("/"):
        route = LearnedRoute(
            domain=domain,
            start_url=url,
            steps=[
                {"action": "goto", "selector": None, "text": None, "url": url},
                {"action": "goto", "selector": None, "text": None, "url": final_page},
            ],
            document_links=[],
            learned_via="cua_final_page",
            confidence=0.2,
            learned_at=_now_iso(),
        )
        log.info("cua_route_learner.learned_final_page", url=url, page=final_page)
        return route

    log.info("cua_route_learner.nothing_replayable", url=url)
    return None


def replay(route: dict, dest_dir: str) -> list[str]:
    """Replay a stored route and download its documents into ``dest_dir``.

    Synchronous (sync Playwright) — call via ``asyncio.to_thread``. Best-effort:
    returns ``[]`` on any failure so the cascade falls through to CUA.
    """
    lr = LearnedRoute.from_dict(route)
    if lr is None or not lr.start_url:
        return []

    try:
        with BrowserSession() as session:
            session.goto(lr.start_url)

            # Re-walk the recorded steps to reach the document page. Both
            # navigation (goto) and click steps must execute — goto steps were
            # previously skipped, which broke every cua_final_page route.
            for step in lr.steps:
                action = step.get("action")
                if action == "goto":
                    target = step.get("url")
                    if target and target.rstrip("/") != lr.start_url.rstrip("/"):
                        try:
                            session.goto(target)
                        except Exception:  # noqa: BLE001
                            continue
                elif action == "click":
                    text = step.get("text")
                    if text:
                        try:
                            session.click_text(text, wait_ms=3000)
                        except Exception:  # noqa: BLE001
                            continue

            # Prefer the document links we recorded; re-harvest if they're gone
            # (the portal may have changed or the links were session-scoped).
            links = list(lr.document_links) or harvest_documents(session)
            if not links:
                log.info("cua_route_learner.replay_no_links", url=lr.start_url)
                return []

            try:
                cookies = session.page.context.cookies()
            except Exception:  # noqa: BLE001
                cookies = []

            saved = download_documents(links, dest_dir, cookies)
            if not saved and lr.document_links:
                # Recorded links can be session-scoped tokens that expired —
                # fall back to whatever the live page offers now.
                fresh = harvest_documents(session)
                if fresh:
                    saved = download_documents(fresh, dest_dir, cookies)
            log.info(
                "cua_route_learner.replay_done",
                url=lr.start_url, links=len(links), saved=len(saved),
            )
            return saved
    except Exception as e:  # noqa: BLE001
        log.warning("cua_route_learner.replay_failed", url=lr.start_url, error=str(e))
        return []
