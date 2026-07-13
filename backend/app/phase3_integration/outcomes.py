"""
Outcome buckets — turn fine-grained failure categories into a small, honest set
of human-readable outcomes, and identify which ones a person can actually fix.

The pipeline already classifies every failure into a detailed
``failure_category`` (see ``core.security.classify_error``). For reporting and
triage we collapse those ~27 categories into a handful of coarse *buckets*, and
flag the ones where a human stepping in (logging in, solving a CAPTCHA) is the
only path forward — surfaced via the "needs manual action" queue.

This is pure mapping logic: no DB, no I/O.
"""
from __future__ import annotations

# success is its own bucket; everything else is a failure family.
SUCCESS = "success"
AUTH_GATED = "auth_gated"
CAPTCHA = "captcha"
EXPIRED = "expired"
UNREACHABLE = "unreachable"
NO_DOCUMENTS = "no_documents"
BLOCKED = "blocked"
ERROR = "error"


# failure_category (from classify_error) → coarse outcome bucket.
OUTCOME_BUCKETS: dict[str, str] = {
    # Access / auth — a human with credentials can resolve these.
    "login_required":        AUTH_GATED,
    "registration_required": AUTH_GATED,
    "auth":                  AUTH_GATED,
    # Bot defense — a human session can resolve these.
    "captcha":               CAPTCHA,
    # Tender lifecycle / gone.
    "expired":               EXPIRED,
    "not_found":             EXPIRED,
    # Infrastructure / transient — site or network problem, retry later.
    "timeout":               UNREACHABLE,
    "network":               UNREACHABLE,
    "dns":                   UNREACHABLE,
    "ssl":                   UNREACHABLE,
    "redirect_loop":         UNREACHABLE,
    "server_error":          UNREACHABLE,
    "rate_limit":            UNREACHABLE,
    "maintenance":           UNREACHABLE,
    "circuit_open":          UNREACHABLE,
    # Content present but nothing downloadable.
    "no_documents":          NO_DOCUMENTS,
    "empty_page":            NO_DOCUMENTS,
    "js_required":           NO_DOCUMENTS,
    "no_strategy":           NO_DOCUMENTS,
    # Security blocks (our own guards).
    "blocked_url":           BLOCKED,
    "prompt_injection":      BLOCKED,
    # Everything else is a genuine error to investigate.
    "code_validation":       ERROR,
    "sandbox":               ERROR,
    "scraper_crash":         ERROR,
    "loop_exhausted":        ERROR,
    "storage":               ERROR,
    "encoding_error":        ERROR,
    "unknown":               ERROR,
}

# Human label per bucket (for dashboards).
BUCKET_LABELS: dict[str, str] = {
    SUCCESS:      "Succeeded",
    AUTH_GATED:   "Login / registration required",
    CAPTCHA:      "CAPTCHA / bot block",
    EXPIRED:      "Expired or not found",
    UNREACHABLE:  "Unreachable (network / server)",
    NO_DOCUMENTS: "No documents found",
    BLOCKED:      "Blocked (security)",
    ERROR:        "Error — needs investigation",
}

# Buckets a human can resolve by intervening directly.
NEEDS_MANUAL: frozenset[str] = frozenset({AUTH_GATED, CAPTCHA})

# Suggested next action shown to operators per bucket.
SUGGESTED_ACTIONS: dict[str, str] = {
    AUTH_GATED:   "Log in or register on the portal (or supply credentials), then retry this URL.",
    CAPTCHA:      "Open the URL in a real browser, clear the CAPTCHA/bot check, then retry.",
    EXPIRED:      "Verify the tender is still open; the documents may have been removed.",
    UNREACHABLE:  "Transient site/network issue — retry later (the circuit breaker will reopen).",
    NO_DOCUMENTS: "Confirm documents are actually published on this page; the link may be a listing.",
    BLOCKED:      "Review the URL — it was blocked by SSRF/security guards.",
    ERROR:        "Inspect the error detail and audit trail for this item.",
}


def bucket_for(failure_category: str | None, success: bool = False) -> str:
    """Map a failure category (and success flag) to a coarse outcome bucket."""
    if success:
        return SUCCESS
    if not failure_category:
        return ERROR
    return OUTCOME_BUCKETS.get(failure_category, ERROR)


def needs_manual(failure_category: str | None) -> bool:
    """True when the failure can only be resolved by a human stepping in."""
    return bucket_for(failure_category) in NEEDS_MANUAL


# failure categories that fall into a needs-manual bucket (for DB filtering).
NEEDS_MANUAL_CATEGORIES: frozenset[str] = frozenset(
    cat for cat, bucket in OUTCOME_BUCKETS.items() if bucket in NEEDS_MANUAL
)
