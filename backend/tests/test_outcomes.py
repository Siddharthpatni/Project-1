"""Tests for outcome bucketing (phase3_integration/outcomes.py)."""
from __future__ import annotations

import pytest

from app.phase3_integration import outcomes as oc


@pytest.mark.parametrize("category,expected", [
    ("login_required", oc.AUTH_GATED),
    ("registration_required", oc.AUTH_GATED),
    ("auth", oc.AUTH_GATED),
    ("captcha", oc.CAPTCHA),
    ("expired", oc.EXPIRED),
    ("not_found", oc.EXPIRED),
    ("timeout", oc.UNREACHABLE),
    ("dns", oc.UNREACHABLE),
    ("server_error", oc.UNREACHABLE),
    ("no_documents", oc.NO_DOCUMENTS),
    ("empty_page", oc.NO_DOCUMENTS),
    ("blocked_url", oc.BLOCKED),
    ("prompt_injection", oc.BLOCKED),
    ("scraper_crash", oc.ERROR),
    ("unknown", oc.ERROR),
])
def test_bucket_for_categories(category, expected):
    assert oc.bucket_for(category) == expected


def test_success_and_empty():
    assert oc.bucket_for(None, success=True) == oc.SUCCESS
    assert oc.bucket_for("anything", success=True) == oc.SUCCESS
    assert oc.bucket_for(None) == oc.ERROR
    assert oc.bucket_for("") == oc.ERROR
    assert oc.bucket_for("some_unmapped_category") == oc.ERROR


def test_needs_manual():
    assert oc.needs_manual("login_required") is True
    assert oc.needs_manual("registration_required") is True
    assert oc.needs_manual("auth") is True
    assert oc.needs_manual("captcha") is True
    # not human-resolvable
    assert oc.needs_manual("timeout") is False
    assert oc.needs_manual("no_documents") is False
    assert oc.needs_manual(None) is False


def test_needs_manual_categories_set():
    assert oc.NEEDS_MANUAL_CATEGORIES == frozenset(
        {"login_required", "registration_required", "auth", "captcha"}
    )


def test_every_classify_error_category_has_a_bucket():
    """Every category classify_error can emit must map to a real (non-fallback
    where intended) bucket — and bucket_for must never raise."""
    documented = [
        "timeout", "network", "dns", "ssl", "redirect_loop", "encoding_error",
        "code_validation", "prompt_injection", "blocked_url", "sandbox",
        "login_required", "registration_required", "auth", "captcha",
        "not_found", "rate_limit", "server_error", "expired", "maintenance",
        "js_required", "empty_page", "scraper_crash", "no_documents", "storage",
        "no_strategy", "loop_exhausted", "unknown",
    ]
    for cat in documented:
        bucket = oc.bucket_for(cat)
        assert bucket in oc.BUCKET_LABELS, f"{cat} -> {bucket} has no label"


def test_all_buckets_have_labels():
    for bucket in {oc.bucket_for(c) for c in oc.OUTCOME_BUCKETS}:
        assert bucket in oc.BUCKET_LABELS
    assert oc.SUCCESS in oc.BUCKET_LABELS
    # needs-manual buckets must have a suggested action
    for b in oc.NEEDS_MANUAL:
        assert b in oc.SUGGESTED_ACTIONS
