"""Tests for the admin API key guard."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.routes_admin import require_admin_key
from app.config import settings


def test_admin_open_when_no_key_configured(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "")
    require_admin_key(authorization=None, x_admin_key=None)  # no exception


def test_admin_rejects_missing_or_wrong_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "sekret")
    for auth, xkey in [(None, None), ("Bearer wrong", None), (None, "wrong")]:
        with pytest.raises(HTTPException) as exc:
            require_admin_key(authorization=auth, x_admin_key=xkey)
        assert exc.value.status_code == 403


def test_admin_accepts_key_via_either_header(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "sekret")
    require_admin_key(authorization="Bearer sekret", x_admin_key=None)
    require_admin_key(authorization=None, x_admin_key="sekret")
