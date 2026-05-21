"""
Discrete action space for computer-use agents.

Every action the LLM can emit is represented as a typed dataclass. The
orchestrator serializes actions to/from JSON so any vision-capable LLM
can drive the agent with a simple tool/function-call schema.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union


@dataclass
class Click:
    type: Literal["click"] = "click"
    x: int = 0
    y: int = 0
    description: str = ""  # human-readable reason, for traces


@dataclass
class Type:
    type: Literal["type"] = "type"
    text: str = ""
    description: str = ""


@dataclass
class Scroll:
    type: Literal["scroll"] = "scroll"
    dy: int = 400  # positive = down
    description: str = ""


@dataclass
class Navigate:
    type: Literal["navigate"] = "navigate"
    url: str = ""
    description: str = ""


@dataclass
class WaitFor:
    type: Literal["wait_for"] = "wait_for"
    selector: str = ""
    timeout_ms: int = 5000
    description: str = ""


@dataclass
class DownloadLink:
    type: Literal["download_link"] = "download_link"
    selector: str = ""  # CSS selector of the link/button to click for download
    description: str = ""


@dataclass
class Finish:
    type: Literal["finish"] = "finish"
    reason: str = ""


Action = Union[Click, Type, Scroll, Navigate, WaitFor, DownloadLink, Finish]


ACTION_SCHEMA = {
    "click":        {"fields": ["x", "y", "description"]},
    "type":         {"fields": ["text", "description"]},
    "scroll":       {"fields": ["dy", "description"]},
    "navigate":     {"fields": ["url", "description"]},
    "wait_for":     {"fields": ["selector", "timeout_ms", "description"]},
    "download_link":{"fields": ["selector", "description"]},
    "finish":       {"fields": ["reason"]},
}


def from_dict(d: dict) -> Action:
    t = d.get("type")
    mapping: dict[str, type] = {
        "click": Click,
        "type": Type,
        "scroll": Scroll,
        "navigate": Navigate,
        "wait_for": WaitFor,
        "download_link": DownloadLink,
        "finish": Finish,
    }

    # Self-healing logic for nested JSON formats emitted by LLMs (e.g. {"scroll": {"dy": 1000}})
    if not t:
        for key in mapping.keys():
            if key in d and isinstance(d[key], dict):
                inner = d[key]
                inner["type"] = key
                d = inner
                t = key
                break

    cls = mapping.get(t)
    if not cls:
        raise ValueError(f"unknown action type: {t}")
    allowed = {k: v for k, v in d.items() if k in ACTION_SCHEMA[t]["fields"] or k == "type"}
    return cls(**allowed)  # type: ignore[arg-type]
