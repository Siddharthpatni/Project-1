"""
Route learner — discover the navigation path from a landing URL to document downloads.

This is the "learn the route once, replay it every time" idea from the
implementation plan: instead of asking the LLM to guess how to navigate
a new portal, we visit it with a real browser, trace the path to the
documents, and record the click sequence. The resulting RouteMap is
then passed to the generator so the produced scraper has an exact,
verified route hardcoded into it.

Detection heuristics (in order):
  1. Direct file links on the landing page.
  2. "Download all" / ZIP buttons by href or visible text.
  3. Tabs/links to dedicated document sections
     ("Unterlagen", "Dokumente", "Vergabeunterlagen", ...).
  4. Detail-page links (when the landing URL is a listing).
  5. Pagination ("Weiter", "Next").

The learner is intentionally bounded: it makes at most 1 hop from the
landing page (one click → look again). Deep traversal isn't this
component's job — when a route can't be learned this way, the cascade
falls back to plain LLM generation, then CUA.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

from app.core.browser_session import BrowserSession
from app.utils.logger import get_logger

log = get_logger(__name__)


# Keywords that suggest a link/button leads to documents.
# Ordered roughly by specificity (most specific first).
_DOCUMENT_NAV_KEYWORDS = [
    # German procurement-specific
    "vergabeunterlagen",
    "unterlagen zur ansicht",
    "alle herunterladen",
    "alle dokumente",
    "alle als zip",
    "unterlagen herunterladen",
    "vergabeunterlagen anfordern",
    "weiter zu den vergabeunterlagen",
    "zip-paket",
    "gesamtpaket",
    "anzeigen",
    # German generic
    "unterlagen",
    "dokumente",
    "herunterladen",
    # English fallback
    "download all",
    "tender documents",
    "documents",
    "download",
]


@dataclass
class RouteStep:
    """One step in a discovered navigation route."""
    action: str                       # "goto" | "click" | "wait"
    selector: str | None = None       # CSS selector for click targets
    text: str | None = None           # human-visible text of the target
    url: str | None = None            # URL for goto / resulting URL after click
    description: str = ""             # human-readable label
    found_downloads: list[str] = field(default_factory=list)


@dataclass
class RouteMap:
    """A traced navigation path from a start URL to document downloads."""
    domain: str
    start_url: str
    steps: list[RouteStep] = field(default_factory=list)
    document_links: list[str] = field(default_factory=list)
    total_documents_found: int = 0
    learned: bool = False            # True if any documents were found
    error: str | None = None
    cua_discovery_report: str | None = None

    def to_dict(self) -> dict:
        d = {
            "domain": self.domain,
            "start_url": self.start_url,
            "steps": [asdict(s) for s in self.steps],
            "document_links": list(self.document_links),
            "total_documents_found": self.total_documents_found,
            "learned": self.learned,
            "error": self.error,
        }
        if self.cua_discovery_report:
            d["cua_discovery_report"] = self.cua_discovery_report
        return d

    def format_for_prompt(self) -> str:
        """Human-readable summary of the route for inclusion in the LLM prompt."""
        if not self.learned or not self.steps:
            return "(no route discovered — generator should infer from page structure)"
        lines = []
        for i, step in enumerate(self.steps, 1):
            if step.action == "goto":
                lines.append(f"  {i}. Navigate to: {step.url}")
            elif step.action == "click":
                target = step.text or step.selector or "(unknown)"
                lines.append(
                    f"  {i}. Click element with text {target!r}"
                    + (f"  [selector: {step.selector}]" if step.selector else "")
                )
            elif step.action == "wait":
                lines.append(f"  {i}. Wait for page to render")
            if step.found_downloads:
                for d in step.found_downloads[:5]:
                    lines.append(f"     → discovered: {d}")
                if len(step.found_downloads) > 5:
                    lines.append(f"     → (+{len(step.found_downloads) - 5} more)")
        lines.append(f"\nTotal documents discovered along this route: {self.total_documents_found}")

        main_summary = "\n".join(lines)
        if self.cua_discovery_report:
            main_summary += f"\n\n## CUA DISCOVERED NAVIGATION ROUTE & ERROR LOGS:\n{self.cua_discovery_report}"
        return main_summary


# ---------------------------------------------------------------------------
# Heuristics for ranking candidate navigation elements
# ---------------------------------------------------------------------------

def _keyword_score(text: str) -> int:
    """Higher score = stronger document-navigation signal."""
    if not text:
        return 0
    t = text.lower()
    for i, kw in enumerate(_DOCUMENT_NAV_KEYWORDS):
        if kw in t:
            # Earlier keywords are more specific → higher score
            return 100 - i
    return 0


def _is_external(href: str, base_domain: str) -> bool:
    try:
        link_domain = urlparse(href).netloc
        if not link_domain:
            return False
        return link_domain != base_domain
    except Exception:
        return True


def _rank_navigation_candidates(
    session: BrowserSession, base_domain: str,
) -> list[tuple[int, dict]]:
    """
    Look at the current page and return candidate elements to click, ranked
    by likelihood of leading to documents. Each candidate is (score, info)
    where info has keys: text, selector, kind ("link"|"button").
    """
    candidates: list[tuple[int, dict]] = []

    # Anchors
    try:
        links = session.get_all_links()
    except Exception as e:  # noqa: BLE001
        log.warning("route_learner.get_links_failed", error=str(e))
        links = []
    for link in links:
        if _is_external(link.get("abs_href", ""), base_domain):
            continue
        text = link.get("text", "")
        score = _keyword_score(text)
        if score <= 0:
            continue
        # Build a text-based selector. Playwright's get_by_text is the
        # actual mechanism we use later; the CSS shown here is informational.
        candidates.append((
            score,
            {
                "kind": "link",
                "text": text.strip()[:80],
                "selector": f"a:has-text({text.strip()[:40]!r})",
                "href": link.get("abs_href", ""),
            },
        ))

    # Buttons (often more specific than anchors)
    try:
        buttons = session.get_buttons()
    except Exception:
        buttons = []
    for btn in buttons:
        text = (btn.get("text") or btn.get("aria_label") or btn.get("name") or "")
        score = _keyword_score(text)
        if score <= 0:
            continue
        # Buttons score 5 points higher than links of the same keyword —
        # they tend to trigger the actual download action.
        candidates.append((
            score + 5,
            {
                "kind": "button",
                "text": text.strip()[:80],
                "selector": f"button:has-text({text.strip()[:40]!r})",
            },
        ))

    # Highest score first
    candidates.sort(key=lambda c: c[0], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def learn_route(url: str, max_clicks: int = 2, headless: bool = True) -> RouteMap:
    """
    Visit `url` with a real browser, look for documents on the landing page,
    and (if none found) follow up to `max_clicks` likely-document navigation
    elements one hop deep. Returns a RouteMap describing what was found.

    Cheap by design: never makes more than `max_clicks + 1` page loads.
    """
    domain = urlparse(url).netloc
    rm = RouteMap(domain=domain, start_url=url)
    rm.steps.append(RouteStep(action="goto", url=url, description="open landing URL"))

    try:
        with BrowserSession(headless=headless) as session:
            try:
                session.goto(url)
            except Exception as e:  # noqa: BLE001
                rm.error = f"goto failed: {e}"
                return rm

            rm.steps.append(RouteStep(action="wait", description="wait for render"))

            # 1) Look on the landing page first.
            initial_downloads = _harvest_downloads(session)
            if initial_downloads:
                rm.steps[-1].found_downloads = initial_downloads
                rm.document_links.extend(initial_downloads)
                rm.total_documents_found = len(rm.document_links)
                rm.learned = True
                log.info(
                    "route_learner.landing_page_has_documents",
                    url=url, count=len(initial_downloads),
                )
                return rm

            # 2) Try the most promising navigation candidates, one click each.
            candidates = _rank_navigation_candidates(session, domain)
            log.info(
                "route_learner.candidates",
                url=url, count=len(candidates),
                top_5=[c[1]["text"] for c in candidates[:5]],
            )

            tried: set[str] = set()
            for _, info in candidates[:max_clicks]:
                key = (info.get("text") or "").lower()
                if not key or key in tried:
                    continue
                tried.add(key)

                # Snapshot pre-click URL so we know if click navigated
                pre_url = session.url()
                clicked = session.click_text(info["text"], wait_ms=3000)
                post_url = session.url()

                step = RouteStep(
                    action="click",
                    selector=info["selector"],
                    text=info["text"],
                    description=f"click {info['kind']}: {info['text']!r}",
                    url=post_url if post_url != pre_url else None,
                )

                if not clicked:
                    log.debug("route_learner.click_failed", text=info["text"])
                    rm.steps.append(step)
                    continue

                downloads = _harvest_downloads(session)
                step.found_downloads = downloads
                rm.steps.append(step)

                if downloads:
                    rm.document_links.extend(d for d in downloads if d not in rm.document_links)
                    rm.total_documents_found = len(rm.document_links)
                    rm.learned = True
                    log.info(
                        "route_learner.found_after_click",
                        url=url, click=info["text"], count=len(downloads),
                    )
                    return rm

            # Nothing found — return an empty but well-formed RouteMap.
            return rm

    except Exception as e:  # noqa: BLE001
        log.exception("route_learner.unexpected_error", url=url)
        rm.error = str(e)
        return rm


def _harvest_downloads(session: BrowserSession) -> list[str]:
    """Collect document URLs visible on the current page.

    Priority: a single ZIP/download-all link if present, otherwise all
    individual document links. This matches the dev branch's proven
    behaviour ("prefer ZIP, fall back to individuals").
    """
    try:
        zip_url = session.find_zip_or_download_all()
        if zip_url:
            return [zip_url]
    except Exception:
        zip_url = None

    try:
        links = session.get_download_links()
    except Exception:
        links = []

    # Filter out obvious non-documents (login, navigation, archive listings)
    clean = []
    skip_patterns = re.compile(r"(login|archivedProcedures|logout)", re.IGNORECASE)
    for href in links:
        if skip_patterns.search(href):
            continue
        clean.append(href)
    return clean
