"""
Typed action descriptors for Phase 2 CUA agents.

These data classes describe the canonical action primitives the CUA produces
during a scraping session. They are used for tracing, evaluation, and for
bridging the raw LLM output to the browser automation layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Click:
    x: int
    y: int
    description: str = ""


@dataclass
class DownloadLink:
    selector: str
    description: str = ""


@dataclass
class Finish:
    reason: str = ""


@dataclass
class Navigate:
    url: str
    description: str = ""


@dataclass
class TypeText:
    selector: str
    text: str
    description: str = ""


@dataclass
class WaitForSelector:
    selector: str
    timeout_ms: int = 5000
    description: str = ""


Action = Click | DownloadLink | Finish | Navigate | TypeText | WaitForSelector


def from_dict(d: dict) -> Action:
    """Deserialise a raw action dict (as returned by the LLM) into a typed action."""
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
