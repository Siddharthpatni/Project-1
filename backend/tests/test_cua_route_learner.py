"""Tests for the CUA route learner (phase2_cua/route_learner.py).

Mirrors the no-DB, boundary-mock style of test_route_and_deterministic.py:
the heuristic tracer (learn_route), the Playwright BrowserSession, and the
httpx downloader are all patched, so these run without Playwright, a browser,
network, or a database.
"""
from __future__ import annotations

from unittest.mock import patch

from app.models import Strategy
from app.phase1_llm_scraper.route_learner import RouteMap, RouteStep
from app.phase2_cua import route_learner as cua_rl
from app.phase2_cua.route_learner import LearnedRoute
from app.phase3_integration import url_intelligence as ui


# ---------------------------------------------------------------------------
# LearnedRoute serialization
# ---------------------------------------------------------------------------

def test_learned_route_roundtrip():
    route = LearnedRoute(
        domain="example.test",
        start_url="https://example.test/notice/1",
        steps=[{"action": "goto", "selector": None, "text": None, "url": "https://example.test/notice/1"},
               {"action": "click", "selector": None, "text": "Vergabeunterlagen", "url": None}],
        document_links=["https://example.test/files.zip"],
        learned_via="cua+trace",
        confidence=0.66,
        learned_at="2026-06-17T00:00:00+00:00",
    )
    restored = LearnedRoute.from_dict(route.to_dict())
    assert restored is not None
    assert restored.domain == "example.test"
    assert restored.document_links == ["https://example.test/files.zip"]
    assert len(restored.steps) == 2
    assert restored.confidence == 0.66


def test_learned_route_from_dict_none_and_malformed():
    assert LearnedRoute.from_dict(None) is None
    assert LearnedRoute.from_dict({}) is None  # empty dict is falsy → None
    # A malformed confidence shouldn't crash — from_dict swallows and returns None.
    bad = LearnedRoute.from_dict({"domain": "x", "confidence": "not-a-number"})
    assert bad is None


# ---------------------------------------------------------------------------
# learn_from_cua
# ---------------------------------------------------------------------------

class _FakeOutcome:
    def __init__(self, trace=None, downloaded_files=None):
        self.trace = trace or []
        self.downloaded_files = downloaded_files or []


def test_learn_from_cua_uses_heuristic_route():
    """A learned RouteMap with document links → a populated LearnedRoute."""
    rm = RouteMap(domain="example.test", start_url="https://example.test/start", learned=True)
    rm.steps = [
        RouteStep(action="goto", url="https://example.test/start"),
        RouteStep(action="wait"),
        RouteStep(action="click", text="Vergabeunterlagen herunterladen"),
    ]
    rm.document_links = ["https://example.test/a.pdf", "https://example.test/b.pdf"]
    rm.total_documents_found = 2

    with patch("app.phase1_llm_scraper.route_learner.learn_route", return_value=rm):
        route = cua_rl.learn_from_cua("https://example.test/start", _FakeOutcome())

    assert route is not None
    assert route.learned_via == "cua+trace"
    assert route.document_links == ["https://example.test/a.pdf", "https://example.test/b.pdf"]
    # Only goto + click steps are kept (the "wait" step is dropped).
    actions = [s["action"] for s in route.steps]
    assert "goto" in actions and "click" in actions and "wait" not in actions
    assert route.confidence > 0


def test_learn_from_cua_salvages_links_from_trace():
    """No replayable click-route, but the CUA trace contains a direct doc URL."""
    rm = RouteMap(domain="example.test", start_url="https://example.test/start", learned=False)
    outcome = _FakeOutcome(trace=[{"state": "downloaded https://example.test/secret/doc.pdf via click"}])

    with patch("app.phase1_llm_scraper.route_learner.learn_route", return_value=rm):
        route = cua_rl.learn_from_cua("https://example.test/start", outcome)

    assert route is not None
    assert route.learned_via == "cua_links"
    assert route.document_links == ["https://example.test/secret/doc.pdf"]
    assert route.steps == [{"action": "goto", "selector": None, "text": None, "url": "https://example.test/start"}]


def test_learn_from_cua_returns_none_when_nothing_replayable():
    """Login-wall case: no heuristic route and no doc URLs anywhere → None."""
    rm = RouteMap(domain="example.test", start_url="https://example.test/start", learned=False)
    outcome = _FakeOutcome(trace=[{"state": "blocked by login form, no documents visible"}])

    with patch("app.phase1_llm_scraper.route_learner.learn_route", return_value=rm):
        route = cua_rl.learn_from_cua("https://example.test/start", outcome)

    assert route is None


# ---------------------------------------------------------------------------
# replay — mocked BrowserSession + downloader
# ---------------------------------------------------------------------------

class _FakeContext:
    def cookies(self):
        return [{"name": "session", "value": "abc"}]


class _FakePage:
    context = _FakeContext()


class _FakeBrowserSession:
    """Minimal BrowserSession stand-in for replay tests."""

    def __init__(self, *, zip_url=None, download_links=None):
        self._zip = zip_url
        self._links = download_links or []
        self.clicked: list[str] = []
        self.page = _FakePage()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def goto(self, url, **kw):
        self._url = url

    def click_text(self, text, wait_ms=0):
        self.clicked.append(text)
        return True

    def find_zip_or_download_all(self):
        return self._zip

    def get_download_links(self):
        return self._links


def test_replay_downloads_stored_links():
    """Stored document_links are downloaded directly; click steps replayed."""
    route = LearnedRoute(
        domain="example.test",
        start_url="https://example.test/start",
        steps=[{"action": "goto", "text": None}, {"action": "click", "text": "Vergabeunterlagen"}],
        document_links=["https://example.test/files.zip"],
    ).to_dict()

    fake_session = _FakeBrowserSession()
    with patch.object(cua_rl, "BrowserSession", return_value=fake_session), \
         patch.object(cua_rl, "download_documents", return_value=["/tmp/files.zip"]) as mock_dl:
        saved = cua_rl.replay(route, "/tmp/replay-dest")

    assert saved == ["/tmp/files.zip"]
    assert fake_session.clicked == ["Vergabeunterlagen"]
    # The stored links (not a re-harvest) were passed to the downloader.
    assert mock_dl.call_args[0][0] == ["https://example.test/files.zip"]


def test_replay_reharvests_when_no_stored_links():
    """When the route has no stored links, replay re-harvests the page."""
    route = LearnedRoute(
        domain="example.test",
        start_url="https://example.test/start",
        steps=[{"action": "goto", "text": None}],
        document_links=[],
    ).to_dict()

    fake_session = _FakeBrowserSession(zip_url="https://example.test/all.zip")
    with patch.object(cua_rl, "BrowserSession", return_value=fake_session), \
         patch.object(cua_rl, "download_documents", return_value=["/tmp/all.zip"]) as mock_dl:
        saved = cua_rl.replay(route, "/tmp/replay-dest")

    assert saved == ["/tmp/all.zip"]
    assert mock_dl.call_args[0][0] == ["https://example.test/all.zip"]


def test_replay_returns_empty_when_no_documents():
    route = LearnedRoute(
        domain="example.test", start_url="https://example.test/start",
        steps=[{"action": "goto", "text": None}], document_links=[],
    ).to_dict()

    fake_session = _FakeBrowserSession()  # no zip, no links
    with patch.object(cua_rl, "BrowserSession", return_value=fake_session):
        saved = cua_rl.replay(route, "/tmp/replay-dest")

    assert saved == []


def test_replay_handles_malformed_route():
    assert cua_rl.replay({}, "/tmp/x") == []
    assert cua_rl.replay({"domain": "x", "start_url": ""}, "/tmp/x") == []


# ---------------------------------------------------------------------------
# Cascade wiring — LEARNED_ROUTE sits right before CUA
# ---------------------------------------------------------------------------

def test_strategy_order_injects_learned_route_before_cua():
    order = ui.get_strategy_order(ui.UrlType.NETSERVER_AUTH, "unknown")
    assert Strategy.LEARNED_ROUTE in order
    assert order.index(Strategy.LEARNED_ROUTE) < order.index(Strategy.CUA)


def test_strategy_order_no_learned_route_when_no_cua():
    # SATELLITE order has no CUA → no LEARNED_ROUTE injected.
    order = ui.get_strategy_order(ui.UrlType.SATELLITE, "dtvp")
    assert Strategy.CUA not in order
    assert Strategy.LEARNED_ROUTE not in order


def test_force_strategy_bypasses_injection():
    order = ui.get_strategy_order(ui.UrlType.UNKNOWN, "unknown", force=Strategy.CUA)
    assert order == [Strategy.CUA]


def test_cascade_order_has_learned_route_before_cua():
    from app.phase3_integration.fallback import CASCADE_ORDER
    assert CASCADE_ORDER.index(Strategy.LEARNED_ROUTE) < CASCADE_ORDER.index(Strategy.CUA)
