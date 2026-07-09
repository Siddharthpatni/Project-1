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

# Injection detection patterns.
# CALIBRATED for German public procurement HTML — patterns must be specific
# enough to avoid false positives in legitimate tender portal content.
# Each pattern is annotated with why it's safe for procurement HTML.
_INJECTION_PATTERNS = [
    # Classic override attempts — very specific phrases unlikely in German procurement
    re.compile(r"ignore (all )?previous (instructions|prompts)", re.IGNORECASE),
    re.compile(r"disregard (all )?(previous |prior |above )?(instructions|prompts|rules)", re.IGNORECASE),

    # "system prompt" only when revealing its content — tightened from
    # the original `system prompt[: ]` which matched "System: Prompt zur Vergabe".
    # Matches: "system prompt is:", "system prompt:", "my system prompt is 'X'"
    # (a bare "system prompt" mention is NOT flagged — it appears in legitimate
    # docs/blog HTML and caused whole domains to be blocked)
    re.compile(r"\bsystem\s+prompt\b[\s:]*(is|was|says|=|:)\s*[\"'`]", re.IGNORECASE),

    # XML-style system tag (not used in German procurement HTML)
    re.compile(r"<\s*system\s*>", re.IGNORECASE),

    # Jailbreak — specific term, no false positives in procurement
    re.compile(r"\bjailbreak\b", re.IGNORECASE),

    # "reveal your instructions / system prompt" — very targeted
    re.compile(r"reveal (your|the) (instructions|system prompt)", re.IGNORECASE),

    # Role-play hijacking — requires a persona word after "you are now"
    re.compile(r"you are now an? (unrestricted|uncensored|evil|different|new) (ai|assistant|model|bot)", re.IGNORECASE),
    re.compile(r"act as (an? )?(different|new|unrestricted|uncensored) (ai|assistant|model|bot)", re.IGNORECASE),

    # Data exfiltration — requires both network verb AND secret keyword
    re.compile(r"\b(curl|wget)\b.*\b(api.?key|secret|token|password)\b", re.IGNORECASE),
    re.compile(r"base64\.b64(encode|decode)", re.IGNORECASE),

    # Encoded hex sequences (≥3 consecutive) — not normal in procurement HTML
    re.compile(r"(?:\\x[0-9a-f]{2}){3,}", re.IGNORECASE),

    # ChatML / separator injection
    re.compile(r"---+\s*\n\s*(system|assistant|user)\s*:", re.IGNORECASE),

    # Inline JS injection with code execution
    re.compile(r"<\s*script[^>]*>.*?\b(eval|exec)\s*\(", re.IGNORECASE | re.DOTALL),
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


# Blocks that carry no signal for scraper generation but are the #1 source of
# injection false positives: minified JS is full of `\x..` escapes, base64
# helpers, and prompt-like strings (SharePoint/SPA bundles tripped the guard
# 5/5 times in the 100-run benchmark on legitimate pages).
_HTML_NOISE = re.compile(
    r"<script\b[^>]*>.*?</script\s*>"
    r"|<style\b[^>]*>.*?</style\s*>"
    r"|<noscript\b[^>]*>.*?</noscript\s*>"
    r"|<!--.*?-->",
    re.IGNORECASE | re.DOTALL,
)


def strip_html_noise(html: str) -> str:
    """Remove script/style/noscript blocks and comments from an HTML payload."""
    return _HTML_NOISE.sub(" ", html)


def redact_injections(text: str) -> tuple[str, list[str]]:
    """Neutralize injection matches in untrusted content instead of rejecting it.

    Returns (redacted_text, hit_patterns). Rejecting the whole page on a match
    punishes legitimate portals; redaction keeps the page usable while the
    generated code is still constrained by the AST validator + sandbox.
    """
    hits: list[str] = []
    for pat in _INJECTION_PATTERNS:
        if pat.search(text):
            hits.append(pat.pattern)
            text = pat.sub("[REDACTED:injection]", text)
    return text, hits


# ---------------------------------------------------------------------------
# Error classification for the admin panel
# ---------------------------------------------------------------------------

_ERROR_CATEGORIES = [
    # --- Infrastructure failures -------------------------------------------------
    (re.compile(r"timeout|timed out|deadline exceeded|read timed out", re.I), "timeout"),
    (re.compile(r"connection (refused|reset|closed|error)|ECONNREFUSED|ECONNRESET|broken pipe", re.I), "network"),
    (re.compile(r"dns|name resolution|getaddrinfo|name or service not known", re.I), "dns"),
    (re.compile(r"ssl|certificate|tls|handshake|self.?signed", re.I), "ssl"),
    (re.compile(r"redirect.?(loop|limit|too many|max)|too many redirects", re.I), "redirect_loop"),
    (re.compile(r"encod|decode|codec|unicode|charmap|utf.?8", re.I), "encoding_error"),

    # --- Security / validation (must come before auth) --------------------------
    (re.compile(r"validation failed|forbidden (import|call)|missing required function", re.I), "code_validation"),
    (re.compile(r"prompt.?inject|injection detected", re.I), "prompt_injection"),
    (re.compile(r"robots\.txt", re.I), "blocked_robots"),
    (re.compile(r"url not allowed|scheme|private network|ssrf", re.I), "blocked_url"),
    (re.compile(r"sandbox|memory limit|killed|oom", re.I), "sandbox"),

    # --- Access / auth ---------------------------------------------------------
    # login_required: page shows a login/registration wall (not a hard 401/403)
    (re.compile(
        r"login.?(required|form|page|redirect)|anmeld|registrier|bitte.?(anmelden|registrieren)"
        r"|sign.?in required|muss.*angemeldet|please log in|account required",
        re.I), "login_required"),
    # registration_required: must register an account to access documents
    (re.compile(
        r"registrierung (erforderlich|notwendig|ben.tigt)|registration required"
        r"|konto erstellen|create.?account|nur.*(registriert|angemeld)",
        re.I), "registration_required"),
    (re.compile(r"(401|403)\b|unauthorized|access denied|forbidden", re.I), "auth"),

    # --- CAPTCHA / bot detection -----------------------------------------------
    (re.compile(r"captcha|recaptcha|hcaptcha|bot.?detection|cloudflare|ddos-guard|cf-ray", re.I), "captcha"),

    # --- HTTP error codes -------------------------------------------------------
    (re.compile(r"404|not found|page not found", re.I), "not_found"),
    (re.compile(r"429|rate.?limit|too many requests", re.I), "rate_limit"),
    (re.compile(r"5\d{2}|server error|internal server|502|503|504|bad gateway|service unavailable", re.I), "server_error"),

    # --- Tender-specific states ------------------------------------------------
    # expired: tender period ended, content archived/removed
    # NOTE: must be "nicht (mehr) verfügbar" — bare "verfügbar" means
    # "available" and misclassified ordinary messages as expired.
    (re.compile(
        r"archiviert|archiv(ed|ierung)|abgelaufen|nicht (mehr )?verf.?gbar|vergabeverfahren.*(beendet|abgeschlossen)"
        r"|tender.*(expired|closed|ended)|ausschreibung.*(beendet|abgelaufen)|frist.*abgelaufen",
        re.I), "expired"),
    # maintenance: site under maintenance
    (re.compile(r"wartung|maintenance|under construction|site.?down|gewartet", re.I), "maintenance"),

    # --- Scraper content issues -----------------------------------------------
    # js_required: page needs JS rendering but scraper used plain HTTP
    (re.compile(r"js.?required|javascript.?(required|enabled|needed)|script.?error|noscript", re.I), "js_required"),
    # empty_page: page loaded but is blank or minimal content
    (re.compile(r"empty.?page|page is empty|no content|blank page|keine (inhalte|daten)", re.I), "empty_page"),
    # scraper_crash: unhandled exception in generated/stored scraper
    (re.compile(r"traceback|unhandled exception|scraper produced no result|crashed|exit code [^0]", re.I), "scraper_crash"),

    # --- Documents / storage --------------------------------------------------
    (re.compile(r"no.?(files|documents|valid)|html_content|too_small", re.I), "no_documents"),
    (re.compile(r"persist failed|s3|storage|upload", re.I), "storage"),

    # --- Pipeline-level states ------------------------------------------------
    (re.compile(r"no template|not deterministic|no runner", re.I), "no_strategy"),
    (re.compile(r"loop exhausted|max.?iterations?", re.I), "loop_exhausted"),
]


def classify_error(error_msg: str | None) -> str:
    """Map a raw error message to a specific failure category.

    Categories (in priority order):
      timeout, network, dns, ssl, redirect_loop, encoding_error,
      code_validation, prompt_injection, blocked_url, sandbox,
      login_required, registration_required, auth,
      captcha, not_found, rate_limit, server_error,
      expired, maintenance, js_required, empty_page, scraper_crash,
      no_documents, storage, no_strategy, loop_exhausted, unknown.
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


def classify_risk(error_msg: str | None) -> str:
    """Classify risk of an error message into low, moderate, or high.

    "high" aborts the whole strategy cascade, so it is reserved for genuine
    security events. auth (401/403) and sandbox limits are NOT high risk:
    an early strategy hitting a "403 Forbidden" used to kill the cascade
    before CUA/MANUAL ran — yet benchmarks show CUA winning exactly those
    auth-gated portals. A sandbox OOM is an LLM-strategy-local failure and
    must not prevent the remaining strategies from trying.
    """
    cat = classify_error(error_msg)
    if cat in {"prompt_injection", "blocked_url"}:
        return "high"
    if cat in {"timeout", "network", "code_validation"}:
        return "moderate"
    return "low"

