"""
Tests for the login-wall parser and the repaired CUA route learner.
"""
from types import SimpleNamespace

from app.core.security import classify_error
from app.phase2_cua.route_learner import (
    _is_document_url,
    _salvage_page_urls_from_outcome,
    learn_from_cua,
)
from app.phase3_integration.login_detector import detect_login_wall


# ---------------------------------------------------------------------------
# Login-wall parser
# ---------------------------------------------------------------------------

_LOGIN_HTML = """
<html><body>
  <h1>Bieterportal</h1>
  <form action="/auth/login" method="post">
    <input type="text" name="user" placeholder="Benutzername">
    <input type="password" name="pass" placeholder="Passwort">
    <button>Anmelden</button>
  </form>
  <a href="/registrieren">Jetzt registrieren</a>
</body></html>
"""

_PUBLIC_WITH_LOGIN_BOX = """
<html><body>
  <div class="header"><form action="/auth/login"><input type="password"></form>Anmelden</div>
  <h1>Vergabeunterlagen</h1>
  <a href="/docs/leistungsbeschreibung.pdf">Leistungsbeschreibung</a>
  <a href="/docs/Vergabeunterlagen.zip">Alle Unterlagen (ZIP)</a>
  <a href="/NetServer/x?function=GetDocumentFile&id=1">Formblatt</a>
</body></html>
"""


def test_hard_login_wall_detected():
    v = detect_login_wall(_LOGIN_HTML)
    assert v.is_wall
    assert v.kind == "login"
    assert v.confidence >= 0.8
    # The formatted error must land in the right failure category.
    assert classify_error(v.as_error()) == "login_required"


def test_public_docs_beat_login_box():
    # A login box in the header must not flag a page full of public documents.
    v = detect_login_wall(_PUBLIC_WITH_LOGIN_BOX)
    assert not v.is_wall


def test_captcha_wall_classifies_as_captcha():
    html = '<html><body><div class="g-recaptcha"></div>Bitte anmelden. Login. Passwort vergessen?</body></html>'
    v = detect_login_wall(html)
    assert v.kind == "captcha"
    assert classify_error(v.as_error()) == "captcha"


def test_empty_or_plain_page_is_not_a_wall():
    assert not detect_login_wall("").is_wall
    assert not detect_login_wall("<html><body><p>Ausschreibung 2026</p></body></html>").is_wall


def test_expired_visibility_notice_detected():
    # Verbatim text observed live on beschaffungen.barmer.de and
    # deutsche-rentenversicherung-bund.de NetServer procedure pages (2026-07-03).
    html = """<html><body><a href="/login">Anmelden</a> Mein Konto Registrierung
    <h2>Bundesweite Lieferung mit Büromöbeln (0020-Büromöbel-2026)</h2>
    <p>Der Sichtbarkeitszeitraum dieser Vergabe ist abgelaufen oder noch nicht erreicht.</p>
    </body></html>"""
    v = detect_login_wall(html)
    assert v.is_wall and v.kind == "expired" and v.confidence >= 0.8
    assert classify_error(v.as_error()) == "expired"


def test_text_gated_documents_detected_without_form():
    # NetServer-style prose wall: no password input on the page, the form
    # lives one click away — the gating is stated in text.
    html = """<html><body><h1>Vergabeunterlagen</h1>
    <p>Um die Vergabeunterlagen herunterzuladen, müssen Sie sich zunächst anmelden.</p>
    <p>Registrierung ist erforderlich. Anmelden</p></body></html>"""
    v = detect_login_wall(html)
    assert v.is_wall
    assert v.kind in ("login", "registration")


def test_eu_supply_deleted_marker_is_expired():
    v = detect_login_wall("<html><body>Error B=TENDERLITE.DELETED</body></html>")
    assert v.is_wall and v.kind == "expired"


# ---------------------------------------------------------------------------
# CUA route learner
# ---------------------------------------------------------------------------

def test_downloadish_urls_count_as_documents():
    assert _is_document_url("https://x.de/files/unterlagen.zip")
    assert _is_document_url("https://x.de/NetServer/x?function=GetDocumentFile&docId=9")
    assert _is_document_url("https://x.de/download?id=42")
    assert not _is_document_url("https://x.de/impressum")


def _fake_outcome(trace_texts):
    return SimpleNamespace(
        trace=[{"step": i, "state": t} for i, t in enumerate(trace_texts)],
        downloaded_files=[],
        success=True,
        error=None,
        steps=len(trace_texts),
    )


def test_salvage_page_urls_same_domain_in_order():
    outcome = _fake_outcome([
        "navigated to https://portal.de/start",
        "clicked tab, now at https://portal.de/tender/123/documents",
        "saw link https://portal.de/files/doc.pdf",           # document — excluded
        "external https://evil.example.com/phish",             # foreign — excluded
    ])
    pages = _salvage_page_urls_from_outcome(outcome, "portal.de")
    assert pages == [
        "https://portal.de/start",
        "https://portal.de/tender/123/documents",
    ]


def test_learn_from_cua_falls_back_to_final_page(monkeypatch):
    # Fresh unauthenticated re-trace fails (as it does on CUA-only portals)…
    import app.phase1_llm_scraper.route_learner as p1rl
    monkeypatch.setattr(p1rl, "learn_route", lambda url: (_ for _ in ()).throw(RuntimeError("wall")))

    outcome = _fake_outcome([
        "goto https://portal.de/entrance",
        "ended on https://portal.de/project/documents",
    ])
    route = learn_from_cua("https://portal.de/entrance", outcome)

    # …but the learner still produces a replayable final-page route.
    assert route is not None
    assert route.learned_via == "cua_final_page"
    goto_urls = [s["url"] for s in route.steps if s["action"] == "goto"]
    assert "https://portal.de/project/documents" in goto_urls


def test_learn_from_cua_returns_none_when_trace_is_empty(monkeypatch):
    import app.phase1_llm_scraper.route_learner as p1rl
    monkeypatch.setattr(p1rl, "learn_route", lambda url: None)
    assert learn_from_cua("https://portal.de/x", _fake_outcome([])) is None
