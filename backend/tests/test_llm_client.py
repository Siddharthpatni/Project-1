"""Tests for the unified LLM client (core/llm_client.py).

Focus: provider routing — "ollama/<name>" models must go to the local Ollama
server (no auth, bare model name, long timeout, $0 cost) while everything
else keeps going to OpenRouter. A fake httpx.AsyncClient captures the wire
request; no network is touched.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from app.config import settings
from app.core import llm_client as lc
from app.core.llm_client import LLMClient, OLLAMA_PREFIX


class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"unexpected HTTP {self.status_code} in test")


class _FakeAsyncClient:
    """Records every POST; always answers 200 with a minimal completion."""

    last: "_FakeAsyncClient | None" = None

    def __init__(self, **kwargs):
        _FakeAsyncClient.last = self
        self.calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "json": json, "headers": headers, "timeout": timeout}
        )
        return _FakeResponse()


@pytest.fixture(autouse=True)
def _no_live_pricing(monkeypatch):
    """Stop the pricing manager from spawning a live OpenRouter fetch."""
    from app.phase1_llm_scraper.pricing import pricing_manager

    monkeypatch.setattr(pricing_manager, "_last_fetched", time.time())


@pytest.fixture()
def fake_http():
    _FakeAsyncClient.last = None
    with patch.object(lc.httpx, "AsyncClient", _FakeAsyncClient):
        yield _FakeAsyncClient


def test_ollama_model_routes_to_local_server(monkeypatch, fake_http):
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama.test:11434/v1")
    client = LLMClient(default_model="ollama/qwen2.5-coder:7b")
    client.api_key = ""  # local models must work without any API key

    resp = asyncio.run(client.chat("sys", "user"))

    call = fake_http.last.calls[0]
    assert call["url"] == "http://ollama.test:11434/v1/chat/completions"
    # Ollama gets the bare model name on the wire …
    assert call["json"]["model"] == "qwen2.5-coder:7b"
    # … but the response keeps the prefixed id for attribution.
    assert resp.model == "ollama/qwen2.5-coder:7b"
    assert "Authorization" not in call["headers"]
    assert call["timeout"] == settings.ollama_timeout_seconds
    assert resp.text == "hello"
    assert resp.cost_usd == 0.0


def test_openrouter_model_keeps_auth_and_default_timeout(fake_http):
    client = LLMClient(default_model="google/gemini-2.5-flash-lite")
    client.api_key = "sk-test"
    client.base_url = "https://openrouter.test/api/v1"

    resp = asyncio.run(client.chat("sys", "user"))

    call = fake_http.last.calls[0]
    assert call["url"] == "https://openrouter.test/api/v1/chat/completions"
    assert call["json"]["model"] == "google/gemini-2.5-flash-lite"
    assert call["headers"]["Authorization"] == "Bearer sk-test"
    assert call["timeout"] == 120
    assert resp.model == "google/gemini-2.5-flash-lite"


def test_openrouter_without_key_returns_stub(fake_http):
    client = LLMClient(default_model="google/gemini-2.5-flash-lite")
    client.api_key = ""

    resp = asyncio.run(client.chat("sys", "user"))

    assert "stub" in resp.text
    assert fake_http.last is None or fake_http.last.calls == []


def test_ollama_prefix_constant():
    """The prefix is public API for callers building model ids."""
    assert OLLAMA_PREFIX == "ollama/"
