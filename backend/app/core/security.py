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
    # Classic override attempts
    re.compile(r"ignore (all )?previous (instructions|prompts)", re.IGNORECASE),
    re.compile(r"disregard (all )?(previous |prior |above )?(instructions|prompts|rules)", re.IGNORECASE),
    re.compile(r"system prompt[: ]", re.IGNORECASE),
    re.compile(r"<\s*system\s*>", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"reveal (your|the) (instructions|system prompt)", re.IGNORECASE),
    # Role-play / persona hijacking
    re.compile(r"you are now (a |an |)", re.IGNORECASE),
    re.compile(r"act as (a |an |)(different|new|unrestricted)", re.IGNORECASE),
    re.compile(r"pretend (you are|to be)", re.IGNORECASE),
    # Data exfiltration
    re.compile(r"(send|post|fetch|curl|wget|http).*(api.key|secret|token|password)", re.IGNORECASE),
    re.compile(r"base64\.b64(encode|decode)", re.IGNORECASE),
    # Encoded / obfuscated instructions
    re.compile(r"\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}.*\\x[0-9a-f]{2}", re.IGNORECASE),
    # Markdown / delimiter injection
    re.compile(r"---+\s*\n\s*(system|assistant|user)\s*:", re.IGNORECASE),
    # Direct code-injection through HTML
    re.compile(r"<\s*script[^>]*>.*?(eval|exec|import|require)\s*\(", re.IGNORECASE | re.DOTALL),
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


# ---------------------------------------------------------------------------
# Error classification for the admin panel
# ---------------------------------------------------------------------------

_ERROR_CATEGORIES = [
    (re.compile(r"timeout|timed out|deadline exceeded", re.I), "timeout"),
    (re.compile(r"connection (refused|reset|closed|error)|ECONNREFUSED|ECONNRESET", re.I), "network"),
    (re.compile(r"dns|name resolution|getaddrinfo", re.I), "dns"),
    (re.compile(r"ssl|certificate|tls", re.I), "ssl"),
    # code_validation MUST come before auth — "forbidden import" ≠ "403 forbidden"
    (re.compile(r"validation failed|forbidden (import|call)|missing required function", re.I), "code_validation"),
    (re.compile(r"(401|403)\b|unauthorized|login required|access denied", re.I), "auth"),
    (re.compile(r"404|not found|page not found", re.I), "not_found"),
    (re.compile(r"429|rate.?limit|too many requests", re.I), "rate_limit"),
    (re.compile(r"5\d{2}|server error|internal server|502|503|504", re.I), "server_error"),
    (re.compile(r"sandbox|memory limit|killed|oom", re.I), "sandbox"),
    (re.compile(r"prompt.?inject|injection detected", re.I), "prompt_injection"),
    (re.compile(r"no.?(files|documents|valid)|html_content|too_small", re.I), "no_documents"),
    (re.compile(r"persist failed|s3|storage|upload", re.I), "storage"),
    (re.compile(r"url not allowed|scheme|private network|ssrf", re.I), "blocked_url"),
    (re.compile(r"no template|not deterministic|no runner", re.I), "no_strategy"),
    (re.compile(r"loop exhausted|max.?iterations?", re.I), "loop_exhausted"),
]


def classify_error(error_msg: str | None) -> str:
    """Map a raw error message to a human-readable category.

    Returns one of: timeout, network, dns, ssl, auth, not_found,
    rate_limit, server_error, code_validation, sandbox,
    prompt_injection, no_documents, storage, blocked_url,
    no_strategy, loop_exhausted, or 'unknown'.
    """
    if not error_msg:
        return "unknown"
    for pat, category in _ERROR_CATEGORIES:
        if pat.search(error_msg):
            return category
    return "unknown"


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
