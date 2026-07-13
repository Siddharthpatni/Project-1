"""Security regression tests for the shared web-harvest download path.

`download_documents` fetches links harvested from *untrusted* portal pages, so it
must (a) never issue a request to a private/internal address — directly or via a
redirect — and (b) never buffer an unbounded body into memory. These tests lock
both guarantees in so a future refactor can't silently reopen the SSRF / memory
holes.
"""
from __future__ import annotations

import httpx

from app.core import web_harvest


def _client(handler) -> httpx.Client:
    """An httpx.Client whose requests are answered by `handler` (no real network).

    Redirects are left disabled (httpx default) — `_guarded_get` follows them
    itself, re-validating every hop.
    """
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_guarded_get_blocks_private_and_metadata_hosts():
    def handler(request):  # pragma: no cover - must never be reached
        raise AssertionError(f"private host should never be requested: {request.url}")

    with _client(handler) as c:
        assert web_harvest._guarded_get(c, "http://169.254.169.254/latest/meta-data/") is None
        assert web_harvest._guarded_get(c, "http://127.0.0.1/admin") is None
        assert web_harvest._guarded_get(c, "http://10.0.0.5/internal") is None
        assert web_harvest._guarded_get(c, "http://localhost:8080/") is None


def test_guarded_get_blocks_non_http_scheme():
    def handler(request):  # pragma: no cover - must never be reached
        raise AssertionError("non-http scheme must never be requested")

    with _client(handler) as c:
        assert web_harvest._guarded_get(c, "file:///etc/passwd") is None
        assert web_harvest._guarded_get(c, "ftp://example.com/x") is None


def test_guarded_get_blocks_redirect_to_internal():
    """A public link that 302-redirects to an internal host must be refused."""
    def handler(request):
        if request.url.host == "portal.example.com":
            return httpx.Response(302, headers={"Location": "http://169.254.169.254/secret"})
        raise AssertionError(f"internal redirect target was fetched: {request.url}")

    with _client(handler) as c:
        assert web_harvest._guarded_get(c, "https://portal.example.com/doc.pdf") is None


def test_guarded_get_follows_external_redirect():
    """A redirect to another *public* host is fine and returns its body."""
    def handler(request):
        if request.url.host == "portal.example.com":
            return httpx.Response(302, headers={"Location": "https://cdn.example.org/real.pdf"})
        return httpx.Response(200, content=b"%PDF-1.4 ok")

    with _client(handler) as c:
        assert web_harvest._guarded_get(c, "https://portal.example.com/doc.pdf") == b"%PDF-1.4 ok"


def test_guarded_get_caps_oversized_body(monkeypatch):
    monkeypatch.setattr(web_harvest, "MAX_DOCUMENT_BYTES", 8)

    def handler(request):
        return httpx.Response(200, content=b"x" * 4096)

    with _client(handler) as c:
        assert web_harvest._guarded_get(c, "https://portal.example.com/huge.zip") is None


def test_guarded_get_stops_redirect_loop():
    def handler(request):
        return httpx.Response(302, headers={"Location": "https://loop.example.com/next"})

    with _client(handler) as c:
        assert web_harvest._guarded_get(c, "https://loop.example.com/start") is None


def test_download_documents_skips_blocked_keeps_valid(tmp_path, monkeypatch):
    # Treat every saved file as a real document so we test the fetch guard, not
    # the file-type validator.
    monkeypatch.setattr(
        "app.phase1_llm_scraper.document_validator.is_real_document_file",
        lambda p: (True, "ok"),
    )

    def handler(request):
        assert request.url.host == "portal.example.com", f"unexpected host {request.url.host}"
        return httpx.Response(200, content=b"%PDF-1.4 real")

    with _client(handler) as c:
        saved = web_harvest.download_documents(
            ["http://127.0.0.1/secret.pdf", "https://portal.example.com/real.pdf"],
            str(tmp_path),
            cookies=[],
            client=c,
        )

    assert len(saved) == 1
    assert saved[0].endswith("real.pdf")
