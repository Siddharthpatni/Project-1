"""Tests for the universal adaptive scraper (phase3_integration/adaptive_scraper.py).

No-DB, boundary-mock style: BrowserSession and the httpx downloader are patched,
so these run without Playwright, a browser, network, or a database. The real
web_harvest heuristics (harvest_documents / rank_nav_candidates / detect_wall)
run against the fake session for genuine integration coverage.
"""
from __future__ import annotations

from unittest.mock import patch

from app.core import web_harvest
from app.models import Strategy
from app.phase3_integration import adaptive_scraper as ad
from app.phase3_integration import url_intelligence as ui
from app.phase3_integration.fallback import CASCADE_ORDER


# ---------------------------------------------------------------------------
# Fake BrowserSession
# ---------------------------------------------------------------------------

class _FakeContext:
    def cookies(self):
        return [{"name": "s", "value": "1"}]


class _FakePage:
    context = _FakeContext()


class _FakeSession:
    """Stateful BrowserSession stand-in: harvest results can change after a click."""

    def __init__(self, *, landing_zip=None, landing_links=None,
                 buttons=None, all_links=None,
                 post_click_zip=None, post_click_links=None, content_text=""):
        self._clicked = False
        self._landing_zip = landing_zip
        self._landing_links = landing_links or []
        self._buttons = buttons or []
        self._all_links = all_links or []
        self._post_click_zip = post_click_zip
        self._post_click_links = post_click_links or []
        self._content = content_text
        self.clicked_texts: list[str] = []
        self.page = _FakePage()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def goto(self, url, **kw):
        self._url = url

    def content(self):
        return self._content

    def find_zip_or_download_all(self):
        return self._post_click_zip if self._clicked else self._landing_zip

    def get_download_links(self):
        return self._post_click_links if self._clicked else self._landing_links

    def get_all_links(self):
        return list(self._all_links)

    def get_buttons(self):
        return list(self._buttons)

    def click_text(self, text, wait_ms=0):
        self._clicked = True
        self.clicked_texts.append(text)
        return True


def _run(session, dl_return=("/tmp/doc.pdf",)):
    with patch.object(ad, "BrowserSession", return_value=session), \
         patch.object(ad, "download_documents", return_value=list(dl_return)) as dl:
        result = ad.run_adaptive("https://example.test/notice/1", "/tmp/adaptive-dest")
    return result, dl


# ---------------------------------------------------------------------------
# run_adaptive
# ---------------------------------------------------------------------------

def test_adaptive_landing_page_success():
    session = _FakeSession(landing_zip="https://example.test/all.zip")
    result, dl = _run(session, dl_return=["/tmp/all.zip"])
    assert result.success is True
    assert result.downloaded_files == ["/tmp/all.zip"]
    assert dl.call_args[0][0] == ["https://example.test/all.zip"]
    assert session.clicked_texts == []  # found on landing, no click needed


def test_adaptive_clicks_through_to_documents():
    """Bare landing page → click the multilingual doc button → find files."""
    session = _FakeSession(
        landing_zip=None,
        buttons=[{"text": "Vergabeunterlagen herunterladen", "name": "", "aria_label": ""},
                 {"text": "Startseite", "name": "", "aria_label": ""}],
        post_click_links=["https://example.test/doc1.pdf", "https://example.test/doc2.pdf"],
    )
    result, dl = _run(session, dl_return=["/tmp/doc1.pdf", "/tmp/doc2.pdf"])
    assert result.success is True
    assert len(result.downloaded_files) == 2
    assert result.clicks >= 1
    assert "Vergabeunterlagen" in session.clicked_texts[0]


def test_adaptive_detects_login_wall():
    """No documents anywhere + a login wall in the page text → precise reason."""
    session = _FakeSession(content_text="You must log in to download these documents.")
    result, dl = _run(session)
    assert result.success is False
    assert "login" in (result.error or "").lower()
    dl.assert_not_called()


def test_adaptive_detects_captcha_wall():
    session = _FakeSession(content_text="Attention Required! Cloudflare — checking your browser")
    result, _ = _run(session)
    assert result.success is False
    assert "captcha" in (result.error or "").lower()


def test_adaptive_generic_no_documents():
    session = _FakeSession(content_text="<html><body>Welcome to the portal</body></html>")
    result, _ = _run(session)
    assert result.success is False
    assert "no downloadable documents" in (result.error or "").lower()


def test_adaptive_page_load_failure_is_handled():
    class _BoomSession(_FakeSession):
        def goto(self, url, **kw):
            raise RuntimeError("net down")

    result, dl = _run(_BoomSession())
    assert result.success is False
    assert "page load failed" in (result.error or "")
    dl.assert_not_called()


# ---------------------------------------------------------------------------
# Cascade wiring
# ---------------------------------------------------------------------------

def test_cascade_has_adaptive_before_llm():
    assert CASCADE_ORDER.index(Strategy.ADAPTIVE) < CASCADE_ORDER.index(Strategy.LLM_GENERATED)
    assert CASCADE_ORDER.index(Strategy.DETERMINISTIC) < CASCADE_ORDER.index(Strategy.ADAPTIVE)


def test_strategy_order_injects_adaptive_before_llm():
    order = ui.get_strategy_order(ui.UrlType.UNKNOWN, "unknown")
    assert Strategy.ADAPTIVE in order
    assert order.index(Strategy.ADAPTIVE) < order.index(Strategy.LLM_GENERATED)


def test_strategy_order_satellite_free_paths_only():
    # SATELLITE order stays free: ADAPTIVE is a deliberate cheap fallback after
    # DETERMINISTIC/EXISTING, but the paid LLM/CUA steps are never reached.
    order = ui.get_strategy_order(ui.UrlType.SATELLITE, "dtvp")
    assert Strategy.LLM_GENERATED not in order
    assert Strategy.CUA not in order
    assert Strategy.ADAPTIVE in order
    assert order.index(Strategy.DETERMINISTIC) < order.index(Strategy.ADAPTIVE)


# ---------------------------------------------------------------------------
# web_harvest multilingual keywords
# ---------------------------------------------------------------------------

def test_keyword_score_multilingual():
    # German, French, Spanish, Italian, Dutch, Polish all score > 0.
    for term in ["Vergabeunterlagen", "Télécharger", "Descargar documentos",
                 "Scarica allegati", "Documenten downloaden", "Pobierz dokumenty"]:
        assert web_harvest.keyword_score(term) > 0
    assert web_harvest.keyword_score("Impressum") == 0
    assert web_harvest.keyword_score("") == 0


def test_detect_wall_categories():
    assert web_harvest.detect_wall("please log in to access") == "login_required"
    assert web_harvest.detect_wall("recaptcha challenge") == "captcha"
    assert web_harvest.detect_wall("registration required to view") == "registration_required"
    assert web_harvest.detect_wall("this tender has expired") == "expired"
    assert web_harvest.detect_wall("just a normal page about services") is None
