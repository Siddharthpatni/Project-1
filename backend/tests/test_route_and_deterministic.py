"""Tests for the new merged components: deterministic strategy and route learner.

These tests mock at the boundary where the merged code meets the
network/browser, so they run without MinIO, Playwright, or LLM access.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.phase1_llm_scraper import route_learner
from app.phase3_integration import deterministic


# ---------------------------------------------------------------------------
# Deterministic strategy
# ---------------------------------------------------------------------------

def test_deterministic_rejects_unknown_platform():
    """Non-deterministic platforms should fail fast with no HTTP request."""
    res = deterministic.try_deterministic("https://random.example.com/page")
    assert res.success is False
    assert "not deterministic" in (res.error or "")
    assert res.downloaded_files == []


def test_deterministic_rejects_dtvp_without_project_id():
    """URL with the right host but no /project/ID won't build a download URL."""
    res = deterministic.try_deterministic(
        "https://vergabe.beispiel.de/Satellite/public/something/else"
    )
    # classify_url returns "unknown" here because there's no /project/ or /notice/ID
    # → the function rejects it as non-deterministic.
    assert res.success is False
    assert res.downloaded_files == []


def test_deterministic_downloads_dtvp_zip(tmp_path):
    """A valid DTVP notice URL should produce a constructed download URL and a saved file."""
    url = "https://vergabe.beispiel.de/Satellite/notice/CXPTEST"
    expected_zip_url = (
        "https://vergabe.beispiel.de/Satellite/public/company/project/CXPTEST"
        "/de/documents/archive/Vergabeunterlagen_CXPTEST.zip"
    )

    # Mock the streaming response — looks like a real ZIP, returns 4 bytes.
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.headers = {"Content-Type": "application/zip"}
    fake_response.iter_content = lambda chunk_size: [b"PK\x03\x04" + b"x" * 250]
    fake_response.__enter__ = lambda self: self
    fake_response.__exit__ = lambda self, *a: False

    with patch.object(deterministic, "_make_output_dir", return_value=tmp_path), \
         patch.object(deterministic.requests, "get", return_value=fake_response) as mock_get:
        res = deterministic.try_deterministic(url)

    assert res.success is True
    assert res.platform == "dtvp"
    assert len(res.downloaded_files) == 1
    saved = res.downloaded_files[0]
    assert saved.endswith(".zip")

    # The constructed URL must match the DTVP template exactly.
    called_url = mock_get.call_args[0][0]
    assert called_url == expected_zip_url


def test_deterministic_treats_404_as_failure(tmp_path):
    """Server says 404 → strategy should fail cleanly, not raise."""
    fake_response = MagicMock()
    fake_response.status_code = 404
    fake_response.headers = {}
    fake_response.iter_content = lambda chunk_size: [b""]
    fake_response.__enter__ = lambda self: self
    fake_response.__exit__ = lambda self, *a: False

    with patch.object(deterministic, "_make_output_dir", return_value=tmp_path), \
         patch.object(deterministic.requests, "get", return_value=fake_response):
        res = deterministic.try_deterministic(
            "https://vergabe.beispiel.de/Satellite/notice/CXMISSING"
        )

    assert res.success is False
    assert res.downloaded_files == []


def test_deterministic_treats_empty_file_as_failure(tmp_path):
    """A 200 OK with zero bytes is not a real download — should fail."""
    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.headers = {"Content-Type": "application/zip"}
    fake_response.iter_content = lambda chunk_size: []
    fake_response.__enter__ = lambda self: self
    fake_response.__exit__ = lambda self, *a: False

    with patch.object(deterministic, "_make_output_dir", return_value=tmp_path), \
         patch.object(deterministic.requests, "get", return_value=fake_response):
        res = deterministic.try_deterministic(
            "https://vergabe.beispiel.de/Satellite/notice/CXEMPTY"
        )

    assert res.success is False


# ---------------------------------------------------------------------------
# Route learner — keyword scoring (pure logic, no browser needed)
# ---------------------------------------------------------------------------

def test_keyword_score_recognizes_german_procurement_terms():
    assert route_learner._keyword_score("Vergabeunterlagen") > 0
    assert route_learner._keyword_score("Alle herunterladen") > 0
    assert route_learner._keyword_score("Unterlagen") > 0


def test_keyword_score_recognizes_english_fallback():
    assert route_learner._keyword_score("Download all") > 0
    assert route_learner._keyword_score("Tender Documents") > 0


def test_keyword_score_ignores_irrelevant_text():
    assert route_learner._keyword_score("Login") == 0
    assert route_learner._keyword_score("Home") == 0
    assert route_learner._keyword_score("") == 0


def test_keyword_score_prefers_more_specific_terms():
    """'vergabeunterlagen' is the most specific keyword → highest score."""
    specific = route_learner._keyword_score("Vergabeunterlagen")
    generic = route_learner._keyword_score("Download")
    assert specific > generic


def test_is_external_detects_cross_domain():
    assert route_learner._is_external("https://other.com/x", "example.com") is True
    assert route_learner._is_external("https://example.com/x", "example.com") is False
    assert route_learner._is_external("/relative/path", "example.com") is False


# ---------------------------------------------------------------------------
# Route learner — full flow with a mocked BrowserSession
# ---------------------------------------------------------------------------

class _FakeSession:
    """A minimal stand-in for BrowserSession used by the route-learner tests."""

    def __init__(self, *, landing_zip=None, landing_downloads=None,
                 landing_links=None, landing_buttons=None,
                 post_click_zip=None, post_click_downloads=None,
                 navigates_on_click=True):
        self._current_url = "https://example.test/start"
        self._post_click = False
        # Pre-click state
        self._landing_zip = landing_zip
        self._landing_downloads = landing_downloads or []
        self._landing_links = landing_links or []
        self._landing_buttons = landing_buttons or []
        # Post-click state
        self._post_click_zip = post_click_zip
        self._post_click_downloads = post_click_downloads or []
        self._navigates_on_click = navigates_on_click

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def goto(self, url, **kw): self._current_url = url
    def url(self): return self._current_url
    def content(self): return "<html></html>"

    def find_zip_or_download_all(self):
        return self._post_click_zip if self._post_click else self._landing_zip

    def get_download_links(self):
        return self._post_click_downloads if self._post_click else self._landing_downloads

    def get_all_links(self): return list(self._landing_links)
    def get_buttons(self): return list(self._landing_buttons)

    def click_text(self, text, wait_ms=0):
        self._post_click = True
        if self._navigates_on_click:
            self._current_url = "https://example.test/after-click"
        return True


def test_route_learner_finds_documents_on_landing_page():
    """If the landing page already has documents, the learner returns immediately."""
    session = _FakeSession(
        landing_zip="https://example.test/files.zip",
    )
    with patch.object(route_learner, "BrowserSession", return_value=session):
        rm = route_learner.learn_route("https://example.test/start")

    assert rm.learned is True
    assert rm.total_documents_found == 1
    assert rm.document_links == ["https://example.test/files.zip"]
    # 2 steps recorded: goto + wait (with downloads attached to the wait step)
    assert any(s.action == "goto" for s in rm.steps)
    assert any(s.found_downloads for s in rm.steps)


def test_route_learner_clicks_through_to_find_documents():
    """Landing page is bare → learner clicks the highest-scored button → finds files."""
    session = _FakeSession(
        landing_zip=None,
        landing_buttons=[
            {"text": "Vergabeunterlagen herunterladen", "name": "", "aria_label": ""},
            {"text": "Home", "name": "", "aria_label": ""},
        ],
        post_click_downloads=[
            "https://example.test/doc1.pdf",
            "https://example.test/doc2.pdf",
        ],
    )
    with patch.object(route_learner, "BrowserSession", return_value=session):
        rm = route_learner.learn_route("https://example.test/start", max_clicks=2)

    assert rm.learned is True
    assert rm.total_documents_found == 2
    assert "https://example.test/doc1.pdf" in rm.document_links

    # A click step should be present with the right target text.
    click_steps = [s for s in rm.steps if s.action == "click"]
    assert len(click_steps) >= 1
    assert "Vergabeunterlagen" in (click_steps[0].text or "")


def test_route_learner_returns_unlearned_when_no_candidates():
    """No documents on the landing page and no nav candidates → return cleanly."""
    session = _FakeSession()  # everything empty
    with patch.object(route_learner, "BrowserSession", return_value=session):
        rm = route_learner.learn_route("https://example.test/start")

    assert rm.learned is False
    assert rm.total_documents_found == 0
    assert rm.error is None  # not an error, just nothing found


def test_route_map_format_for_prompt_renders_steps():
    """The string sent to the LLM should describe the discovered route in a readable way."""
    session = _FakeSession(landing_zip="https://example.test/x.zip")
    with patch.object(route_learner, "BrowserSession", return_value=session):
        rm = route_learner.learn_route("https://example.test/start")

    rendered = rm.format_for_prompt()
    assert "https://example.test/start" in rendered
    assert "https://example.test/x.zip" in rendered
    assert "Total documents" in rendered


def test_route_map_format_for_prompt_handles_no_route():
    """When nothing was learned, the rendered string says so — doesn't crash."""
    session = _FakeSession()
    with patch.object(route_learner, "BrowserSession", return_value=session):
        rm = route_learner.learn_route("https://example.test/start")

    rendered = rm.format_for_prompt()
    assert "no route discovered" in rendered.lower()


def test_normalize_url_eu_supply_entrance_to_public():
    """EU-Supply login-entrance URLs are rewritten to the public tender page."""
    from app.phase3_integration.platform_classifier import normalize_url
    src = "http://eu.eu-supply.com/app/rfq/rwlentrance_s.asp?PID=455767&B=TENDERLITE.DELETED"
    assert normalize_url(src) == "http://eu.eu-supply.com/ctm/Supplier/PublicPurchase/455767/0/0"
    # Non-entrance URLs pass through untouched.
    keep = "https://ausschreibungen.giz.de/Satellite/notice/CXTRYY6YTVGFLGE9/documents"
    assert normalize_url(keep) == keep
