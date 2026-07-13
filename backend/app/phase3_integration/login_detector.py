"""
Login-wall parser — structural detection of auth walls from raw HTML.

The benchmarks showed 57/100 LLM runs failing with "ran, but no documents"
against pages that were simply login walls. Detecting the wall *before*
spending LLM tokens (and reporting it honestly) is cheaper and clearer than
letting a generated scraper wander a sign-in page.

Pure regex over the HTML — no browser, no BeautifulSoup, ~microseconds.
Multilingual (DE/EN/FR/ES/IT/NL/PL/PT) since the pipeline targets portals
across the EU.

Verdict semantics:
  * ``is_wall``     — page is dominated by an auth wall.
  * ``kind``        — "login" | "registration" | "captcha".
  * ``confidence``  — 0..1; ≥ 0.8 means "hard wall, skip paid strategies".
  * ``evidence``    — human-readable signals for the audit trail.

A page can show a login box AND public documents (many portals do); document
links are a strong negative signal, so such pages are NOT flagged as walls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Positive signals ─────────────────────────────────────────────────────────

_PASSWORD_INPUT = re.compile(r"<input[^>]+type\s*=\s*[\"']?password", re.IGNORECASE)

_LOGIN_FORM_ACTION = re.compile(
    r"<form[^>]+action\s*=\s*[\"'][^\"']*(login|signin|sign-in|anmeld|logon|auth)[^\"']*[\"']",
    re.IGNORECASE,
)

# Visible login vocabulary across the EU portal languages we scrape.
_LOGIN_WORDS = re.compile(
    r"\b("
    r"anmelden|einloggen|login|log\s?in|sign\s?in|kennwort|passwort"          # DE/EN
    r"|se\s+connecter|connexion|mot\s+de\s+passe"                              # FR
    r"|iniciar\s+sesi[oó]n|contrase[nñ]a"                                      # ES
    r"|accedi|accesso"                                                          # IT
    r"|inloggen|wachtwoord"                                                     # NL
    r"|zaloguj|has[lł]o"                                                        # PL
    r"|entrar|iniciar\s+sess[aã]o"                                              # PT
    r")\b",
    re.IGNORECASE,
)

_REGISTRATION_WORDS = re.compile(
    r"\b("
    r"registrieren|registrierung|konto\s+erstellen"                             # DE
    r"|register|create\s+(an\s+)?account|sign\s?up"                             # EN
    r"|s'inscrire|inscription|cr[eé]er\s+un\s+compte"                           # FR
    r"|registrarse|crear\s+cuenta"                                              # ES
    r"|registrati|zarejestruj"                                                  # IT/PL
    r")\b",
    re.IGNORECASE,
)

_CAPTCHA_MARKERS = re.compile(
    r"recaptcha|hcaptcha|cf-turnstile|cf_chl|captcha", re.IGNORECASE
)

# Auth requirement stated in prose rather than as an embedded form — common on
# NetServer procedure pages where the login form lives on a separate page.
_TEXT_GATED = re.compile(
    r"(anmeldung|registrierung)\s+(ist\s+)?(erforderlich|notwendig|ben[oö]tigt)"
    r"|nur\s+(f[uü]r\s+)?(registrierte|angemeldete)"
    r"|(um|zum)\s+[^.<]{0,80}(herunterzuladen|einzusehen|teilzunehmen)[^.<]{0,60}(anmelden|registrieren)"
    r"|m[uü]ssen\s+sie\s+sich\s+[^.<]{0,40}(anmelden|registrieren)"
    r"|(please|must)\s+(log\s?in|sign\s?in|register)\s+to\s+(view|download|access)",
    re.IGNORECASE,
)

# Explicit expiry / visibility notices — observed verbatim on live NetServer
# portals ("Der Sichtbarkeitszeitraum dieser Vergabe ist abgelaufen oder noch
# nicht erreicht.") and EU-Supply deleted tenders. 3/20 benchmark domains were
# expired; without this the LLM still burned iterations against them.
_EXPIRED_NOTICE = re.compile(
    r"sichtbarkeitszeitraum[^.<]{0,60}(abgelaufen|nicht\s+erreicht)"
    r"|(vergabe|ausschreibung|verfahren|angebotsfrist|frist)[^.<]{0,40}"
    r"(abgelaufen|beendet|abgeschlossen|geschlossen|archiviert)"
    r"|nicht\s+(mehr\s+)?verf[uü]gbar"
    r"|tender\s+(has\s+)?(expired|closed|ended|been\s+(deleted|removed))"
    r"|no\s+longer\s+available"
    r"|TENDERLITE\.DELETED",
    re.IGNORECASE,
)

# ── Negative signals — public documents on the page ─────────────────────────

_DOC_LINK = re.compile(
    r"href\s*=\s*[\"'][^\"']*"
    r"(\.pdf|\.zip|\.docx?|\.xlsx?|\.gaeb|\.x8[13]"
    r"|download|getdocument|documentfile|unterlagen|attachment)"
    r"[^\"']*[\"']",
    re.IGNORECASE,
)


@dataclass
class LoginWallVerdict:
    is_wall: bool
    kind: str | None = None            # "login" | "registration" | "captcha"
    confidence: float = 0.0
    evidence: list[str] = field(default_factory=list)

    def as_error(self) -> str:
        """Format so classify_error() maps to the matching failure category."""
        detail = "; ".join(self.evidence[:3]) or "auth wall detected"
        if self.kind == "expired":
            return f"tender expired: {detail}"
        if self.kind == "captcha":
            return f"captcha detected: {detail}"
        if self.kind == "registration":
            # classify_error expects "registration required" with a space
            return f"registration required: {detail}"
        return f"login_required: {detail}"


def detect_login_wall(html: str | None) -> LoginWallVerdict:
    """Parse raw HTML and decide whether the page is a hard auth wall."""
    if not html:
        return LoginWallVerdict(is_wall=False)

    sample = html[:200_000]
    evidence: list[str] = []
    score = 0.0
    kind: str | None = None

    # Explicit expiry notice wins outright — the portal states the tender is
    # gone, so document links / login boxes elsewhere on the page are noise.
    m = _EXPIRED_NOTICE.search(sample)
    if m:
        return LoginWallVerdict(
            is_wall=True,
            kind="expired",
            confidence=0.9,
            evidence=[f"expiry notice on page: \"{m.group(0)[:100]}\""],
        )

    if _PASSWORD_INPUT.search(sample):
        score += 0.55
        kind = "login"
        evidence.append("password input field present")

    if _LOGIN_FORM_ACTION.search(sample):
        score += 0.25
        kind = kind or "login"
        evidence.append("form posts to a login/auth endpoint")

    login_hits = len(_LOGIN_WORDS.findall(sample))
    if login_hits >= 2:
        score += 0.20
        kind = kind or "login"
        evidence.append(f"{login_hits} login-vocabulary matches")

    if _REGISTRATION_WORDS.search(sample):
        score += 0.10
        if kind is None:
            kind = "registration"
        evidence.append("registration prompt present")

    if _TEXT_GATED.search(sample):
        # "Registrierung erforderlich" / "must sign in to download" — the wall
        # is stated in prose even though the form lives on another page.
        score += 0.45
        kind = kind or "login"
        evidence.append("page text states documents require login/registration")

    if _CAPTCHA_MARKERS.search(sample):
        score += 0.35
        kind = "captcha"
        evidence.append("CAPTCHA / bot-challenge markers")

    # Public documents on the page beat the wall signals: portals often show a
    # login box in the header while the tender documents are freely linked.
    doc_links = len(_DOC_LINK.findall(sample))
    if doc_links:
        score -= 0.5 + min(doc_links, 5) * 0.1
        evidence.append(f"{doc_links} public document link(s) present — not a hard wall")

    confidence = max(0.0, min(1.0, score))
    return LoginWallVerdict(
        is_wall=confidence >= 0.6 and kind is not None,
        kind=kind,
        confidence=round(confidence, 2),
        evidence=evidence,
    )
