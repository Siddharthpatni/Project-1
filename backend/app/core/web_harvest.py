"""
Shared, language-agnostic web-harvesting helpers for procurement portals.

Centralizes the "find the documents, then download them" primitives that several
strategies need (the CUA route learner replay and the universal adaptive
scraper), plus a multilingual keyword set so the heuristics work on portals in
any country — not just the German/English ones the original route learner knew.

Everything here is pure Playwright (via the shared BrowserSession) + httpx — no
LLM, no vision model. Helpers never raise; they return empty results on trouble
so callers can fall through the cascade cleanly.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from app.core.security import is_url_allowed
from app.utils.logger import get_logger

log = get_logger(__name__)


# File extensions we treat as real procurement documents.
DOC_SUFFIXES = (
    ".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx", ".odt", ".ods", ".xml", ".rar", ".7z", ".csv",
)

# Document-navigation keywords across many languages, ordered roughly by
# specificity (most specific first → highest score). These match link/button
# text or hrefs that lead to tender documents. Lowercase; matched as substrings.
DOC_NAV_KEYWORDS: list[str] = [
    # ── German ────────────────────────────────────────────────────────────
    "vergabeunterlagen", "ausschreibungsunterlagen", "alle herunterladen",
    "alle dokumente", "alle als zip", "unterlagen herunterladen",
    "gesamtpaket", "zip-paket", "downloadbereich", "unterlagen", "dokumente",
    "anlagen", "herunterladen",
    # ── English ───────────────────────────────────────────────────────────
    "tender documents", "procurement documents", "bid documents",
    "download all", "download documents", "all documents", "attachments",
    "documents", "download", "files",
    # ── French ────────────────────────────────────────────────────────────
    "dossier de consultation", "règlement de consultation", "pièces jointes",
    "pièces du marché", "télécharger", "documents", "pièces", "dce",
    # ── Spanish ───────────────────────────────────────────────────────────
    "documentación", "pliego de condiciones", "pliegos", "descargar",
    "anexos", "expediente", "documentos",
    # ── Portuguese ────────────────────────────────────────────────────────
    "peças do procedimento", "descarregar", "baixar", "edital", "anexos",
    "documentos",
    # ── Italian ───────────────────────────────────────────────────────────
    "documenti di gara", "disciplinare", "scaricare", "allegati", "bando",
    "scarica", "documenti",
    # ── Dutch ─────────────────────────────────────────────────────────────
    "aanbestedingsstukken", "downloaden", "bijlagen", "documenten", "stukken",
    # ── Polish ────────────────────────────────────────────────────────────
    "dokumenty zamówienia", "specyfikacja", "załączniki", "pobierz",
    "dokumenty", "siwz",
    # ── Nordic (SV/DA/NO/FI) ──────────────────────────────────────────────
    "förfrågningsunderlag", "ladda ner", "hämta", "bilagor", "last ned",
    "hent", "vedlegg", "dokumenter", "asiakirjat", "lataa", "liitteet",
    "dokument",
    # ── Generic ───────────────────────────────────────────────────────────
    "zip", "package", "paket",
]

# Strong, unambiguous signals that a page gates its content behind a wall.
# Used only to *explain* a no-document outcome (never to abort early), so
# over-firing can't cost us a winnable download.
_WALL_SIGNALS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"recaptcha|hcaptcha|h-captcha|cf-challenge|cf-ray|ddos-guard"
                r"|checking your browser|verify you are human|are you a robot"
                r"|attention required.*cloudflare", re.I), "captcha"),
    (re.compile(r"bitte.{0,3}(melden sie sich an|anmelden)|anmeldung erforderlich"
                r"|please (log ?in|sign ?in) to (view|access|download)"
                r"|you must (log ?in|be logged in)|veuillez vous connecter"
                r"|inicie sesión para|debe iniciar sesión"
                r"|login required to|sign in required", re.I), "login_required"),
    (re.compile(r"registrierung (erforderlich|notwendig)|registration (is )?required"
                r"|create an account to (view|access|download)"
                r"|nur für (registrierte|angemeldete)|must register to", re.I),
     "registration_required"),
    (re.compile(r"verfahren.{0,5}(beendet|abgeschlossen)|ausschreibung.{0,5}(beendet|abgelaufen)"
                r"|tender (has )?(expired|closed|ended)|frist (ist )?abgelaufen"
                r"|no longer available|nicht mehr verfügbar", re.I), "expired"),
]

# URL fragments that are never tender documents (login/admin/nav noise).
_SKIP_HREF = re.compile(
    r"(login|logout|signin|sign-in|register|registr|anmeld|datenschutz|impress"
    r"|privacy|cookie|/agb|archivedProcedures)",
    re.IGNORECASE,
)


def keyword_score(text: str) -> int:
    """Higher score = stronger document-navigation signal. 0 = no signal."""
    if not text:
        return 0
    t = text.lower()
    for i, kw in enumerate(DOC_NAV_KEYWORDS):
        if kw in t:
            return len(DOC_NAV_KEYWORDS) - i  # earlier (more specific) → higher
    return 0


def _is_external(href: str, base_domain: str) -> bool:
    try:
        link_domain = urlparse(href).netloc
        return bool(link_domain) and link_domain != base_domain
    except Exception:  # noqa: BLE001
        return True


def harvest_documents(session) -> list[str]:
    """Collect document URLs on the current page (prefer a single ZIP-all).

    Mirrors the proven "prefer ZIP, fall back to individual links" behaviour and
    filters out login/nav noise. Never raises.
    """
    try:
        zip_url = session.find_zip_or_download_all()
        if zip_url:
            return [zip_url]
    except Exception:  # noqa: BLE001
        pass
    try:
        links = session.get_download_links()
    except Exception:  # noqa: BLE001
        links = []
    return [h for h in links if not _SKIP_HREF.search(h)]


def rank_nav_candidates(session, base_domain: str, limit: int = 4) -> list[dict]:
    """Rank on-page links/buttons by likelihood of leading to documents.

    Returns up to `limit` candidate dicts ({kind, text, href}) highest-score
    first. Multilingual via `keyword_score`. Never raises.
    """
    scored: list[tuple[int, dict]] = []

    try:
        links = session.get_all_links()
    except Exception:  # noqa: BLE001
        links = []
    for link in links:
        href = link.get("abs_href", "")
        if _is_external(href, base_domain) or _SKIP_HREF.search(href):
            continue
        text = (link.get("text") or "").strip()
        score = keyword_score(text) or (keyword_score(href) // 2)
        if score > 0:
            scored.append((score, {"kind": "link", "text": text[:80], "href": href}))

    try:
        buttons = session.get_buttons()
    except Exception:  # noqa: BLE001
        buttons = []
    for btn in buttons:
        text = (btn.get("text") or btn.get("aria_label") or btn.get("name") or "").strip()
        score = keyword_score(text)
        if score > 0:
            # Buttons usually trigger the actual download → slight boost.
            scored.append((score + 2, {"kind": "button", "text": text[:80], "href": ""}))

    scored.sort(key=lambda c: c[0], reverse=True)
    # de-dupe by visible text, preserve order
    seen: set[str] = set()
    out: list[dict] = []
    for _, info in scored:
        key = info["text"].lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(info)
        if len(out) >= limit:
            break
    return out


def detect_wall(page_text: str) -> str | None:
    """Return a precise gating reason (captcha/login_required/…) or None.

    Conservative: only fires on strong, unambiguous signals. Intended to
    *explain* a no-document outcome, not to abort a run early.
    """
    if not page_text:
        return None
    for pat, reason in _WALL_SIGNALS:
        if pat.search(page_text):
            return reason
    return None


# Hard cap on a single document's size. Defends against a hostile portal serving
# a multi-GB body to exhaust worker memory. Procurement ZIP bundles are large but
# realistically well under this.
MAX_DOCUMENT_BYTES = 100 * 1024 * 1024  # 100 MB
_MAX_REDIRECTS = 5


def _guarded_get(client: httpx.Client, url: str) -> bytes | None:
    """Fetch ``url`` defensively and return its body, or ``None`` if it can't be
    safely retrieved.

    The links downloaded here are harvested from an *untrusted* portal page, so
    each is treated as hostile:

    * **SSRF** — every URL, and every redirect hop, is checked with
      ``is_url_allowed`` before any request is made. Redirects are followed
      manually (the client has them disabled) so an attacker can't bounce us from
      a public link to ``127.0.0.1`` / cloud-metadata / another internal host.
    * **Resource exhaustion** — the body is streamed and aborted past
      ``MAX_DOCUMENT_BYTES`` (and rejected up front on an honest Content-Length).

    One retry on transient transport errors keeps flaky portals winnable.
    """
    for attempt in (1, 2):
        try:
            return _guarded_get_once(client, url)
        except httpx.TransportError as e:
            if attempt == 2:
                raise
            log.debug("web_harvest.retry", url=url[:200], error=type(e).__name__)
            time.sleep(0.5)
    return None


def _guarded_get_once(client: httpx.Client, url: str) -> bytes | None:
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        allowed, reason = is_url_allowed(current)
        if not allowed:
            log.warning("web_harvest.blocked_url", url=current[:200], reason=reason)
            return None
        with client.stream("GET", current, follow_redirects=False) as r:
            if r.is_redirect:
                location = r.headers.get("Location")
                if not location:
                    return None
                current = urljoin(current, location)
                continue
            if r.status_code != 200:
                return None
            declared = r.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > MAX_DOCUMENT_BYTES:
                log.warning("web_harvest.too_large", url=current[:200], bytes=declared)
                return None
            chunks: list[bytes] = []
            total = 0
            for chunk in r.iter_bytes():
                total += len(chunk)
                if total > MAX_DOCUMENT_BYTES:
                    log.warning("web_harvest.too_large_stream", url=current[:200])
                    return None
                chunks.append(chunk)
            return b"".join(chunks)
    log.warning("web_harvest.too_many_redirects", url=url[:200])
    return None


def download_documents(
    urls: list[str],
    dest_dir: str,
    cookies: list[dict] | None,
    *,
    client: httpx.Client | None = None,
) -> list[str]:
    """Download `urls` into `dest_dir` using the browser session cookies.

    Each link is fetched through ``_guarded_get`` (SSRF-checked, redirect-safe,
    size-capped). Keeps only files that pass `is_real_document_file` (same gate
    the sandbox executor applies) so login/HTML error pages aren't counted as
    documents. Never raises; returns the list of saved absolute paths.

    `client` is injectable for testing; when omitted a session-scoped client is
    created (redirects disabled — ``_guarded_get`` follows them safely itself).
    """
    from app.phase1_llm_scraper.document_validator import is_real_document_file  # noqa: PLC0415

    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)

    cookie_jar = {c.get("name"): c.get("value") for c in (cookies or []) if c.get("name")}
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.8,fr;q=0.7,es;q=0.6",
    }

    owns_client = client is None
    if owns_client:
        client = httpx.Client(
            timeout=30, follow_redirects=False, cookies=cookie_jar, headers=headers,
        )

    saved: list[str] = []
    seen_names: set[str] = set()
    try:
        for i, link in enumerate(urls):
            try:
                content = _guarded_get(client, link)
                if not content:
                    continue
                name = Path(urlparse(link).path).name or f"document_{i}"
                if "." not in name:
                    name = f"{name}.bin"
                candidate = name
                n = 1
                while candidate in seen_names or (dest / candidate).exists():
                    stem, _, ext = name.rpartition(".")
                    candidate = f"{stem}__{n}.{ext}" if stem else f"{name}__{n}"
                    n += 1
                out = dest / candidate
                out.write_bytes(content)
                ok, reason = is_real_document_file(str(out))
                if ok:
                    seen_names.add(candidate)
                    saved.append(str(out))
                else:
                    log.debug("web_harvest.rejected", link=link, reason=reason)
                    try:
                        out.unlink()
                    except OSError:
                        pass
            except Exception as e:  # noqa: BLE001
                log.debug("web_harvest.download_failed", link=link, error=str(e))
                continue
    finally:
        if owns_client:
            client.close()
    return saved
