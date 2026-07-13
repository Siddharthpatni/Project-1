"""
Typed action descriptors for Phase 2 CUA agents.

These dataclasses represent the canonical browser actions the CUA can produce
during a scraping session. They serve three purposes:

  1. Tracing — each action is recorded in the AgentRunOutcome.trace list and
     later persisted to the agent_runs table, giving a full audit trail of what
     the agent did and why.

  2. Evaluation — the harness can count action types to assess agent efficiency
     (e.g. how many clicks before first download).

  3. Bridging — the `from_dict` function converts the raw dict returned by the
     LLM into a typed action the browser layer can pattern-match on safely.

NOTE: These descriptors are used for tracing/evaluation only. The actual browser
automation in browser_agent.py / browser_use_agent.py is driven by the browser-use
library's own internal action parser — not by these classes directly.
"""
from __future__ import annotations

from dataclasses import dataclass


# ── Browser Action Types ───────────────────────────────────────────────────────

@dataclass
class Click:
    """Click at absolute pixel coordinates (vision-model output)."""
    x: int
    y: int
    description: str = ""   # human-readable label for trace readability


@dataclass
class DownloadLink:
    """
    Click a CSS selector and wait for a file download.
    Used when the agent identifies a specific download button by DOM selector
    rather than by pixel coordinates.
    """
    selector: str
    description: str = ""


@dataclass
class Finish:
    """
    Signal that the agent considers the task complete.
    The `reason` field is logged to the trace so operators can understand
    whether the agent succeeded, found no documents, or hit an error wall.
    """
    reason: str = ""


@dataclass
class Navigate:
    """Navigate the browser to a specific URL.

    Used when the agent needs to jump to a sub-page (e.g. a document listing
    tab) directly rather than clicking a visible link.
    """
    url: str
    description: str = ""


@dataclass
class TypeText:
    """Type text into a form field identified by CSS selector.

    Primarily used for search fields on portals that require entering a
    project reference number to access the document listing.
    """
    selector: str
    text: str
    description: str = ""


@dataclass
class WaitForSelector:
    """
    Pause until a CSS selector appears in the DOM.

    Used after triggering an async action (e.g. clicking a tab that loads
    a document list via AJAX) to ensure the agent doesn't attempt to
    interact with elements that haven't rendered yet.
    """
    selector: str
    timeout_ms: int = 5000   # 5s default — most AJAX responses arrive within 2s
    description: str = ""


# ── Union type ─────────────────────────────────────────────────────────────────

# All concrete action types collected into a single union. Used for type annotations
# in functions that accept or return any action.
Action = Click | DownloadLink | Finish | Navigate | TypeText | WaitForSelector


# ── Deserialiser ───────────────────────────────────────────────────────────────

def from_dict(d: dict) -> Action:
    """
    Deserialise a raw action dict (as returned by the LLM or stored in a trace)
    into a typed action dataclass.

    Expected format:
        {"type": "click", "x": 100, "y": 200, "description": "Download button"}
        {"type": "navigate", "url": "https://...", "description": "..."}
        {"type": "download_link", "selector": ".btn-download", ...}
        {"type": "type_text", "selector": "#search", "text": "project-123", ...}
        {"type": "wait_for_selector", "selector": ".doc-list", "timeout_ms": 3000}
        {"type": "finish", "reason": "all downloads triggered"}

    Raises ValueError for unknown action types so the caller knows the LLM
    returned something unexpected.
    """
    action_type = d.get("type", "")

    if action_type == "click":
        return Click(x=int(d.get("x", 0)), y=int(d.get("y", 0)), description=d.get("description", ""))

    if action_type == "download_link":
        return DownloadLink(selector=d.get("selector", ""), description=d.get("description", ""))

    if action_type == "finish":
        return Finish(reason=d.get("reason", ""))

    if action_type == "navigate":
        return Navigate(url=d.get("url", ""), description=d.get("description", ""))

    if action_type == "type_text":
        return TypeText(
            selector=d.get("selector", ""),
            text=d.get("text", ""),
            description=d.get("description", ""),
        )

    if action_type == "wait_for_selector":
        return WaitForSelector(
            selector=d.get("selector", ""),
            timeout_ms=int(d.get("timeout_ms", 5000)),
            description=d.get("description", ""),
        )

    raise ValueError(f"unknown action type: {action_type!r}")
