"""
Security primitives: prompt-injection detection and URL allowlisting.

These are the guardrails required by Phase 1 — specifically for:
- unsafe generated code            (handled by phase1_llm_scraper.validator + sandbox)
- prompt injection from web content (this module)
- unauthorized system access       (sandbox + URL allowlist below)
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

# Blatant injection patterns. Not a full defense — just a tripwire.
_INJECTION_PATTERNS = [
    re.compile(r"ignore (all )?previous (instructions|prompts)", re.IGNORECASE),
    re.compile(r"system prompt[: ]", re.IGNORECASE),
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"reveal (your|the) (instructions|system prompt)", re.IGNORECASE),
]

# Schemes that must never appear in a generated scraper target URL.
_BAD_SCHEMES = {"file", "ftp", "gopher", "javascript", "data"}

# Private network ranges — block SSRF attempts.
_PRIVATE_NET_PATTERNS = [
    re.compile(r"^127\."),
    re.compile(r"^10\."),
    re.compile(r"^192\.168\."),
    re.compile(r"^172\.(1[6-9]|2[0-9]|3[0-1])\."),
    re.compile(r"^169\.254\."),
    re.compile(r"^0\."),
    re.compile(r"^localhost$", re.IGNORECASE),
    re.compile(r"^::1$"),
]


def detect_prompt_injection(text: str) -> list[str]:
    """Return a list of hit patterns (empty if none)."""
    hits: list[str] = []
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            hits.append(pat.pattern)
    return hits


def sanitize_web_content(text: str, max_length: int = 8000) -> str:
    """Truncate + mark untrusted content so LLMs treat it as data, not instructions."""
    snippet = text[:max_length]
    return f"<untrusted_web_content>\n{snippet}\n</untrusted_web_content>"


def is_url_allowed(url: str) -> tuple[bool, str]:
    """Return (allowed, reason). Block SSRF and non-HTTP schemes."""
    try:
        parsed = urlparse(url)
    except Exception as e:  # noqa: BLE001
        return False, f"parse error: {e}"

    if parsed.scheme not in {"http", "https"}:
        return False, f"scheme not allowed: {parsed.scheme}"
    if parsed.scheme in _BAD_SCHEMES:
        return False, f"scheme blocked: {parsed.scheme}"

    host = (parsed.hostname or "").lower()
    for pat in _PRIVATE_NET_PATTERNS:
        if pat.match(host):
            return False, f"private network blocked: {host}"

    return True, "ok"
