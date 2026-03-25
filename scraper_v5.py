#!/usr/bin/env python3
"""
scraper.py — German public procurement tender scraper
======================================================

A single-file scraper that loads German procurement tender pages,
extracts structured data (via XPath or LLM), recovers broken URLs,
and optionally downloads tender documents.

Merged from scraper_v3, scraper_v4, and vergabe24_token modules.

Usage examples:
    # Phase 1 — XPath only, no LLM, quick scan
    python scraper.py -i tenders.csv -n 50

    # Phase 2 — LLM-assisted extraction
    python scraper.py -i tenders.csv --llm --api-key YOUR_KEY

    # With document downloads, organised by company name
    python scraper.py -i tenders.csv --llm --download-docs --folder-by-company

Requirements:
    pip install playwright openai requests
    playwright install chromium
"""

import asyncio
import argparse
import csv
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import quote, quote_plus, unquote, urljoin, urlparse

import requests

# ---------------------------------------------------------------------------
# Encoding fix for Windows terminals
# ---------------------------------------------------------------------------
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.FileHandler("scraper.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("scraper")


# ═══════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════

# LLM model chain — cheapest first, fall back on failure
MODEL_CHAIN = [
    "google/gemini-2.5-flash-lite",
    "qwen/qwen3-14b",
]

# Global run statistics (populated during execution)
STATS = {
    "total_calls": 0,
    "retries": 0,
    "total_tokens": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_cost": 0.0,
    "calls_per_domain": {},
    "model_usage": {},
    "url_recoveries": {},
}


# ═══════════════════════════════════════════════════════════════════════════
#  RESULT SCHEMA
# ═══════════════════════════════════════════════════════════════════════════

def empty_result(row: dict, domain: str) -> dict:
    """Return a blank result dict with all expected keys."""
    return {
        "id":              row.get("id", ""),
        "url":             row.get("url", ""),
        "url_used":        None,
        "domain":          domain,
        "status":          "pending",
        "title":           None,
        "authority":       None,
        "description":     None,
        "deadline":        None,
        "pub_date":        None,
        "proc_type":       None,
        "cpv":             None,
        "location":        None,
        "ref_num":         None,
        "contact":         None,
        "model_used":      None,
        "llm_tokens":      0,
        "llm_cost":        0.0,
        "downloaded_docs": [],
        "url_recovery":    None,
        "err":             None,
        "ms":              0,
        "ts":              "",
    }


# ═══════════════════════════════════════════════════════════════════════════
#  VERGABE24 URL RECOVERY
# ═══════════════════════════════════════════════════════════════════════════
#
#  Many vergabe24.de / tender24.de URLs expire quickly. We try to find a
#  working URL by: (1) hitting alternative NetServer endpoints directly,
#  (2) searching DuckDuckGo, (3) searching Google as a last resort.
# ═══════════════════════════════════════════════════════════════════════════

NETSERVER_URL_TEMPLATES = [
    "https://www.vergabe24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
    "https://www.vergabe24.de/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0",
    "https://europa.vergabe24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
    "https://europa.vergabe24.de/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0",
    "https://www.tender24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

TENDER_CONTENT_KEYWORDS = [
    "auftraggeber", "vergabe", "leistung", "frist",
    "bekanntmachung",
]


def extract_tender_id(url: str) -> Optional[str]:
    """
    Pull the tender ID out of any vergabe24 / tender24 URL.

    Handles both the /vergabeunterlagen/54321-Tender-… format and
    the ?TenderOID=54321-Tender-… query-string format.
    """
    match = re.search(
        r"(54321-(?:Tender|PublishingProcess)-[a-f0-9][a-f0-9\-]+)",
        url, re.IGNORECASE,
    )
    return match.group(1) if match else None


def _try_netserver_urls(tender_id: str, timeout: int = 10) -> Optional[str]:
    """Hit each NetServer URL template and return the first one that works."""
    for template in NETSERVER_URL_TEMPLATES:
        url = template.format(tid=tender_id)
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout,
                                allow_redirects=True)
            if resp.status_code != 200 or len(resp.text) < 500:
                continue

            body = resp.text.lower()
            has_content = any(kw in body for kw in TENDER_CONTENT_KEYWORDS)
            has_id = tender_id.lower() in body
            if has_content or has_id:
                log.info(f"  [recovery] NetServer URL works: {url}")
                return url
        except Exception as exc:
            log.debug(f"  [recovery] {url} → {str(exc)[:60]}")
    return None


def _search_duckduckgo(tender_id: str, timeout: int = 10) -> Optional[str]:
    """Search DuckDuckGo's HTML endpoint for a vergabe24 link containing the tender ID."""
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(tender_id)}"
    try:
        resp = requests.get(search_url, headers=BROWSER_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None

        for href in re.findall(r'href="(https?://[^"]+)"', resp.text):
            netloc = urlparse(href).netloc.lower()
            if "vergabe24" in netloc or "tender24" in netloc:
                if not any(skip in href for skip in ["duckduckgo", "google", "bing", "/search"]):
                    log.info(f"  [DDG] found: {href}")
                    return href
    except Exception as exc:
        log.debug(f"  [DDG] error: {str(exc)[:80]}")
    return None


def _search_google(tender_id: str, timeout: int = 10) -> Optional[str]:
    """Google fallback — less reliable due to bot detection, but worth a shot."""
    query = f'site:vergabe24.de OR site:tender24.de "{tender_id}"'
    search_url = f"https://www.google.com/search?q={quote_plus(query)}&num=5"
    try:
        resp = requests.get(search_url, headers=BROWSER_HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return None

        patterns = [
            r'/url\?q=(https?://(?:www\.|europa\.)?(?:vergabe24|tender24)\.de[^&"]+)',
            r'href="(https?://(?:www\.|europa\.)?(?:vergabe24|tender24)\.de[^"]+)"',
        ]
        for pat in patterns:
            for match in re.findall(pat, resp.text):
                clean = unquote(match)
                if tender_id.lower() in clean.lower():
                    log.info(f"  [Google] found: {clean}")
                    return clean
    except Exception as exc:
        log.debug(f"  [Google] error: {str(exc)[:80]}")
    return None


def recover_vergabe24_url(original_url: str) -> dict:
    """
    Given an expired vergabe24 URL, try to find a working replacement.

    Returns a dict with keys: tender_id, original_url, found_url, strategy.
    """
    result = {
        "tender_id":    None,
        "original_url": original_url,
        "found_url":    None,
        "strategy":     None,
    }

    tender_id = extract_tender_id(original_url)
    if not tender_id:
        log.warning(f"  [recovery] cannot extract Tender ID from: {original_url}")
        return result

    result["tender_id"] = tender_id
    log.info(f"  [recovery] Tender ID: {tender_id}")

    # Strategy 1 — alternative NetServer endpoints
    found = _try_netserver_urls(tender_id)
    if found:
        result["found_url"] = found
        result["strategy"] = "netserver"
        return result

    # Strategy 2 — DuckDuckGo search
    found = _search_duckduckgo(tender_id)
    if found:
        result["found_url"] = found
        result["strategy"] = "duckduckgo"
        return result

    # Strategy 3 — Google search
    found = _search_google(tender_id)
    if found:
        result["found_url"] = found
        result["strategy"] = "google"
        return result

    log.warning(f"  [recovery] tender {tender_id} not found via any strategy")
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  URL NORMALISATION & PORTAL REWRITING
# ═══════════════════════════════════════════════════════════════════════════

def fix_double_encoding(url: str) -> str:
    """
    Fix URLs where percent signs got double-encoded (%2520 → %20).
    This happens with certain evergabe.de portals.
    """
    fixed = re.sub(r"%25([0-9A-Fa-f]{2})", r"%\1", url)
    if fixed != url:
        log.debug("  url fix: double-encoding corrected")
    return fixed


def strip_documents_suffix(url: str) -> Optional[str]:
    """Remove a trailing /documents from a portal notice URL."""
    clean = re.sub(r"/documents/?$", "", url, flags=re.IGNORECASE)
    return clean if clean != url else None


def portal_rewrite(url: str) -> List[str]:
    """
    Generate alternative URLs for known German procurement portal patterns.
    Returns a de-duplicated list (most likely to work first).
    """
    alternatives = []
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path   = parsed.path
    query  = parsed.query

    # --- bieterzugang.deutsche-evergabe.de ---
    if "bieterzugang.deutsche-evergabe.de" in netloc:
        sid = None
        m = re.search(r"/subproject/([0-9a-f-]{36})", path)
        m2 = re.search(r"subProjectId=([^&]+)", query)
        if m:
            sid = m.group(1)
        elif m2:
            sid = m2.group(1)

        if sid:
            alternatives += [
                sid,
                f"https://www.deutsche-evergabe.de/dashboards/DetailsDashboard/{sid}",
                f"https://www.deutsche-evergabe.de/vergabe/detail/{sid}",
                f"https://bieterzugang.deutsche-evergabe.de/evergabe.bieter/DownloadTenderFiles.ashx?subProjectId={sid}",
            ]

    # --- auftraege.bayern.de ---
    if "auftraege.bayern.de" in netloc:
        m = re.search(r"([0-9a-f-]{36})", path)
        if m:
            sid = m.group(1)
            alternatives += [
                f"https://www.auftraege.bayern.de/dashboards/dashboard_off/{sid}",
                f"https://www.auftraege.bayern.de/evergabe.bieter/DownloadTenderFiles.ashx?subProjectId={sid}",
            ]

    # --- evergabe.bayern.de deep-links ---
    if "evergabe.bayern.de" in netloc and "/deeplink/subproject/" in path:
        m = re.search(r"/subproject/([0-9a-f-]{36})", path)
        if m:
            uuid = m.group(1)
            alternatives += [
                f"https://www.evergabe.bayern.de/tenderdetails/{uuid}",
                f"https://www.evergabe.bayern.de/vergabe/{uuid}",
            ]

    # --- NetServer (tender24, vergabe.fraunhofer, had, etc.) ---
    if "PublicationControllerServlet" in path or "TenderingProcedureDetails" in path:
        oid_match = re.search(r"TWOID=([^&]+)", query) or re.search(r"TenderOID=([^&]+)", query)
        if oid_match:
            val = oid_match.group(1)
            base = f"{parsed.scheme}://{parsed.netloc}"
            alternatives += [
                f"{base}/NetServer/PublicationControllerServlet?function=Detail&TWOID={val}&PublicationType=0",
                f"{base}/NetServer/PublicationControllerServlet?function=Detail&TWOID={val}&PublicationType=4",
                f"{base}/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={val}",
                f"{base}/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={val}&view=documents",
            ]

    # --- vergabe24.de / tender24.de ---
    if "vergabe24.de" in netloc or "tender24.de" in netloc:
        m = re.search(r"(54321-Tender-[a-f0-9-]+)", path)
        if m:
            tid = m.group(1)
            base = f"{parsed.scheme}://{parsed.netloc}"
            alternatives += [
                f"{base}/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
                f"{base}/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0",
                f"https://europa.vergabe24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
                f"https://europa.vergabe24.de/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0",
            ]

    # --- subreport.de ---
    if "subreport.de" in netloc:
        m = re.search(r"/E(\d+)$", path)
        if m:
            alternatives.append(f"https://www.subreport.de/E{m.group(1)}")

    # De-duplicate while preserving order, exclude the original URL
    seen = {url}
    unique = []
    for alt in alternatives:
        if alt not in seen:
            seen.add(alt)
            unique.append(alt)
    return unique


def build_search_query(row: dict, original_url: str) -> str:
    """Build a search-engine query to relocate a tender page."""
    parsed = urlparse(original_url)
    domain = parsed.netloc.replace("www.", "")
    path   = parsed.path

    # Try to pull a meaningful identifier from the URL
    tid = None
    m = re.search(r"(54321-(?:Tender|PublishingProcess)-[a-f0-9-]+)", original_url, re.IGNORECASE)
    if m:
        tid = m.group(1)

    if not tid:
        m = re.search(r"/E(\d{6,10})$", path)
        if m:
            tid = "E" + m.group(1)

    if not tid:
        m = re.search(r"/notice/([A-Z0-9]{6,20})", path)
        if m:
            tid = m.group(1)

    if not tid:
        m = re.search(r"/(\d{6,10})$", path)
        if m:
            tid = m.group(1)

    if tid:
        return f'site:{domain} "{tid}"'

    # No ID found — use last path segment as a hint
    authority_hint = re.sub(r"[^\w\s]", " ", unquote(path).split("/")[-2])[:40]
    return f"site:{domain} {authority_hint} ausschreibung"


# ═══════════════════════════════════════════════════════════════════════════
#  PAGE CLASSIFICATION (login walls, gone pages)
# ═══════════════════════════════════════════════════════════════════════════

LOGIN_WALL_PHRASES = [
    "bitte melden sie sich an", "please log in", "login required",
    "session abgelaufen", "session expired", "ihre sitzung ist abgelaufen",
    "zugangsdaten", "passwort eingeben", "anmelden, um", "zugang gesperrt",
    "sicherheitsabfrage", "captcha", "not authorized", "403 forbidden",
    "zugang verweigert", "sie sind nicht eingeloggt",
]

GONE_PHRASES = [
    "nicht mehr verfügbar", "nicht gefunden", "abgelaufen",
    "seite existiert nicht", "page not found",
    "vergabe wurde aufgehoben", "bekanntmachung wurde gelöscht",
    "kein ergebnis", "kein treffer", "404", "403 forbidden",
    "diese ausschreibung existiert nicht",
    "could not extract tender id",
    "there is no documents section",
]


def is_login_wall(text: str) -> bool:
    """Return True if the page looks like it's behind a login / session wall."""
    snippet = text.lower()[:3000]
    return any(phrase in snippet for phrase in LOGIN_WALL_PHRASES)


def is_gone(text: str) -> bool:
    """Return True if the page says the tender has been removed or expired."""
    snippet = text.lower()[:6000]
    return any(phrase in snippet for phrase in GONE_PHRASES)


# ═══════════════════════════════════════════════════════════════════════════
#  COOKIE BANNER DISMISSAL
# ═══════════════════════════════════════════════════════════════════════════

COOKIE_BUTTON_SELECTORS = [
    "xpath=//button[contains(text(),'Akzeptieren')]",
    "xpath=//button[contains(text(),'Alle akzeptieren')]",
    "xpath=//button[contains(text(),'Annehmen')]",
    "xpath=//button[contains(text(),'Accept')]",
    "xpath=//button[contains(text(),'Zustimmen')]",
    "xpath=//button[contains(text(),'Nur notwendige')]",
    "xpath=//button[contains(text(),'Einverstanden')]",
    "xpath=//button[contains(@class,'accept') or contains(@class,'consent')]",
    "xpath=//button[@id='accept' or @id='acceptCookies' or @id='cookieAccept']",
    "xpath=//a[contains(text(),'Akzeptieren') or contains(text(),'Accept')]",
    "xpath=//button[contains(@class,'cookie') and contains(@class,'btn')]",
]


async def dismiss_cookies(page) -> bool:
    """Try to click a cookie-consent button. Returns True if one was clicked."""
    for selector in COOKIE_BUTTON_SELECTORS:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=500):
                await btn.click()
                await page.wait_for_timeout(500)
                return True
        except Exception:
            pass
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  PAGE TEXT EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════

async def get_page_text(page, max_chars: int = 8000) -> str:
    """
    Grab the visible text from the page body.
    Scrolls to the bottom first to trigger lazy-loaded content.
    """
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(300)
        await page.evaluate("window.scrollTo(0, 0)")
    except Exception:
        pass

    try:
        text = await page.inner_text("body")
    except Exception:
        return ""

    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" {2,}", " ", text).strip()

    # JS-heavy pages sometimes need an extra moment
    if len(text) < 100:
        await page.wait_for_timeout(2000)
        try:
            text = await page.inner_text("body")
            text = re.sub(r"\n{3,}", "\n\n", text)
            text = re.sub(r" {2,}", " ", text).strip()
        except Exception:
            pass

    return text[:max_chars]


# ═══════════════════════════════════════════════════════════════════════════
#  SEARCH-ENGINE FALLBACK  (uses DuckDuckGo via the browser)
# ═══════════════════════════════════════════════════════════════════════════

async def browser_search_for_url(page, query: str) -> Optional[str]:
    """Open DuckDuckGo in the browser tab, scrape the first relevant link."""
    search_url = f"https://duckduckgo.com/?q={quote(query)}&ia=web"
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1500)
        await dismiss_cookies(page)
        await page.wait_for_timeout(500)

        for link in await page.locator("xpath=//a[@href]").all():
            try:
                href = await link.get_attribute("href")
                if not href:
                    continue
                if any(x in href for x in ["duckduckgo.com", "google.com", "bing.com", "javascript:", "#"]):
                    continue
                parsed = urlparse(href)
                if parsed.scheme in ("http", "https") and parsed.netloc:
                    log.info(f"    🔍 search fallback found: {href[:80]}")
                    return href
            except Exception:
                pass
    except Exception as exc:
        log.debug(f"    search failed: {str(exc)[:60]}")
    return None


# ═══════════════════════════════════════════════════════════════════════════
#  PAGE LOADING — FULL RECOVERY CHAIN
# ═══════════════════════════════════════════════════════════════════════════

async def load_with_recovery(page, row: dict) -> Tuple[str, str, Optional[str]]:
    """
    Try to load the tender page, cycling through several fallback strategies
    if the original URL fails. Returns (page_text, final_url, recovery_label).
    """
    original_url = row.get("url", "").strip()

    # -- inner helper: attempt a single URL ----------------------------------
    async def try_url(url: str, label: str, timeout: int = 15000):
        sniffed_url = None

        def catch_request(req):
            nonlocal sniffed_url
            if "token=" in req.url and "europa.vergabe24.de" in req.url:
                sniffed_url = req.url

        page.on("request", catch_request)
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            await dismiss_cookies(page)

            # vergabe24 / tender24 pages do a JS redirect that adds a token
            if "vergabe24.de" in url or "tender24.de" in url:
                for _ in range(12):
                    if "token=" in page.url or sniffed_url:
                        break
                    await page.wait_for_timeout(1000)
                    await dismiss_cookies(page)

                if sniffed_url and "token=" not in page.url:
                    await page.goto(sniffed_url, wait_until="domcontentloaded", timeout=timeout)
                    await dismiss_cookies(page)

                await page.wait_for_timeout(1500)
            else:
                await page.wait_for_timeout(1000)

            final_url = page.url
            if resp and resp.status >= 400 and not ("token=" in final_url or ".ashx" in final_url):
                return None

            await dismiss_cookies(page)
            text = await get_page_text(page)

            is_download_link = any(x in final_url.lower() for x in (".ashx", ".php", ".zip", ".pdf", "/download"))
            if not text or len(text) < 50:
                return ("DOWNLOAD_LINK", final_url) if is_download_link else None
            if is_login_wall(text):
                return None
            if is_gone(text):
                return None

            return text, final_url

        except Exception as exc:
            log.debug(f"    {label} failed: {str(exc)[:60]}")
            return None
        finally:
            page.remove_listener("request", catch_request)

    # -- recovery chain ------------------------------------------------------
    normalized = fix_double_encoding(original_url)

    # Special handling for vergabe24 / tender24 — try HTTP recovery first
    domain_check = urlparse(normalized).netloc.lower()
    if "vergabe24" in domain_check or "tender24" in domain_check:
        recovery = recover_vergabe24_url(normalized)
        if recovery["found_url"]:
            log.info(f"    🔄 vergabe24 recovery: {recovery['found_url'][:80]}")
            res = await try_url(recovery["found_url"], "vergabe24-netserver")
            if res:
                return res[0], res[1], f"vergabe24_{recovery['strategy']}"

    # Attempt 1: normalised URL
    res = await try_url(normalized, "original")
    if res:
        return res[0], res[1], None

    # Attempt 2: strip /documents suffix
    stripped = strip_documents_suffix(normalized)
    if stripped:
        res = await try_url(stripped, "strip-/documents")
        if res:
            return res[0], res[1], "strip_documents"

    # Attempt 3: portal-specific URL rewrites
    for alt in portal_rewrite(normalized):
        res = await try_url(alt, "portal-rewrite")
        if res:
            return res[0], res[1], "portal_rewrite"

    # Attempt 4: try the raw (un-normalised) URL if it differs
    if normalized != original_url:
        res = await try_url(original_url, "original-raw")
        if res:
            return res[0], res[1], "original_raw"

    # Attempt 5: search engine fallback
    query = build_search_query(row, normalized)
    log.info(f"    🔍 trying search fallback: {query}")
    found_url = await browser_search_for_url(page, query)
    if found_url and found_url != normalized:
        res = await try_url(found_url, "search-fallback")
        if res:
            return res[0], res[1], "search_fallback"

    # All strategies exhausted
    return "", original_url, None


# ═══════════════════════════════════════════════════════════════════════════
#  XPATH DATA EXTRACTION  (Phase 1)
# ═══════════════════════════════════════════════════════════════════════════

FIELD_XPATHS = {
    "title": [
        "//h1",
        "//*[contains(@class,'title') and (self::h1 or self::h2)]",
        "//title",
    ],
    "authority": [
        "//dt[contains(.,'Auftraggeber')]/following-sibling::dd[1]",
        "//th[contains(.,'Auftraggeber')]/following-sibling::td[1]",
        "//td[contains(.,'Auftraggeber')]/following-sibling::td[1]",
        "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
        "//*[contains(text(),'Vergabestelle')]/following-sibling::*[1]",
        "//*[contains(@class,'vergabestelle')]",
        "//*[contains(@class,'auftraggeber')]",
    ],
    "description": [
        "//*[contains(text(),'Beschreibung') or contains(text(),'Leistung')]/following-sibling::*[1]",
        "//*[contains(@class,'description')]",
        "//*[contains(@class,'leistung')]",
    ],
    "deadline": [
        "//dt[contains(.,'Angebotsfrist') or contains(.,'Frist')]/following-sibling::dd[1]",
        "//th[contains(.,'Frist')]/following-sibling::td[1]",
        "//td[contains(.,'Frist')]/following-sibling::td[1]",
        "//*[contains(text(),'Angebotsfrist') or contains(text(),'Teilnahmefrist')]/following-sibling::*[1]",
        "//*[contains(text(),'Abgabetermin')]/following-sibling::*[1]",
        "//span[contains(@id,'Frist') or contains(@id,'frist')]",
    ],
    "pub_date": [
        "//dt[contains(.,'Veröffentlich')]/following-sibling::dd[1]",
        "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
        "//*[contains(text(),'Bekanntmachung')]/following-sibling::*[1]",
    ],
    "proc_type": [
        "//dt[contains(.,'Verfahrensart') or contains(.,'Vergabeart')]/following-sibling::dd[1]",
        "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
    ],
    "cpv": [
        "//*[contains(text(),'CPV')]/following-sibling::*[1]",
        "//dt[contains(.,'CPV')]/following-sibling::dd[1]",
    ],
    "location": [
        "//*[contains(text(),'Erfüllungsort') or contains(text(),'Ort der Leistung')]/following-sibling::*[1]",
        "//dt[contains(.,'Ort')]/following-sibling::dd[1]",
    ],
    "ref_num": [
        "//dt[contains(.,'Vergabenummer') or contains(.,'Aktenzeichen')]/following-sibling::dd[1]",
        "//*[contains(text(),'Vergabenummer') or contains(text(),'Aktenzeichen')]/following-sibling::*[1]",
    ],
    "contact": [
        "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
        "//*[contains(@class,'contact')]",
    ],
}


async def _xpath_get_first(page, xpaths: list) -> Optional[str]:
    """Try each XPath in order, return the first non-empty text match."""
    for xp in xpaths:
        try:
            elements = await page.locator(f"xpath={xp}").all()
            if elements:
                txt = (await elements[0].inner_text()).strip()
                if txt and len(txt) < 2000:
                    return txt
        except Exception:
            pass
    return None


async def xpath_extract(page) -> dict:
    """
    Extract tender data from the page using XPath selectors.
    Falls back to scanning <dt>/<dd> pairs if the main selectors miss.
    """
    extracted = {}
    for field, xpaths in FIELD_XPATHS.items():
        value = await _xpath_get_first(page, xpaths)
        if value:
            extracted[field] = value

    # Fallback: scan definition lists for known German labels
    if not extracted.get("title") and not extracted.get("authority"):
        try:
            for dt in await page.locator("xpath=//dt").all():
                label = (await dt.inner_text()).strip()
                value = await dt.evaluate("el => el.nextElementSibling?.textContent?.trim()")
                if not label or not value or len(label) >= 150:
                    continue

                label_lower = label.lower()
                if "auftraggeber" in label_lower or "vergabestelle" in label_lower:
                    extracted.setdefault("authority", value)
                elif "frist" in label_lower or "angebotsfrist" in label_lower:
                    extracted.setdefault("deadline", value)
                elif "veröffentlich" in label_lower:
                    extracted.setdefault("pub_date", value)
                elif "verfahren" in label_lower or "vergabeart" in label_lower:
                    extracted.setdefault("proc_type", value)
        except Exception:
            pass

    return extracted


# ═══════════════════════════════════════════════════════════════════════════
#  LLM DATA EXTRACTION  (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════

LLM_EXTRACTION_PROMPT = """Extract procurement tender data from this German page text.
URL: {url}

PAGE TEXT:
{text}

Return ONLY valid JSON. No markdown, no backticks, no explanation.
Use null for missing fields.

{{"title":"tender title","authority":"Auftraggeber/Vergabestelle","description":"what is being procured (2-3 sentences max)","deadline":"Angebotsfrist/Teilnahmefrist date","pub_date":"Veröffentlichungsdatum","proc_type":"Verfahrensart","cpv":"CPV codes if present","location":"Erfüllungsort","ref_num":"Vergabenummer/Aktenzeichen","contact":"contact name/email/phone"}}"""


def extract_with_llm(client, page_text: str, url: str, domain: str,
                     model_chain: list = None) -> Tuple[Optional[dict], Optional[str], int, float]:
    """
    Send the page text to an LLM and parse the returned JSON.
    Walks through the model chain on failure. Returns (data, model_name, tokens, cost).
    """
    if model_chain is None:
        model_chain = MODEL_CHAIN

    prompt = LLM_EXTRACTION_PROMPT.format(url=url, text=page_text)
    STATS["total_calls"] += 1
    STATS["calls_per_domain"].setdefault(domain, 0)
    STATS["calls_per_domain"][domain] += 1

    for model in model_chain:
        for attempt in range(2):
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "Extract structured data from German procurement pages. Return ONLY valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0,
                    max_tokens=1000,
                )

                tokens = 0
                cost = 0.0
                if resp.usage:
                    tokens = resp.usage.total_tokens or 0
                    STATS["total_tokens"] += tokens
                    STATS["prompt_tokens"] += resp.usage.prompt_tokens or 0
                    STATS["completion_tokens"] += resp.usage.completion_tokens or 0
                    if hasattr(resp.usage, "cost") and resp.usage.cost:
                        cost = float(resp.usage.cost)
                        STATS["total_cost"] += cost

                STATS["model_usage"].setdefault(model, 0)
                STATS["model_usage"][model] += 1

                raw = (resp.choices[0].message.content or "").strip()
                # Strip markdown code fences that some models add
                if raw.startswith("```"):
                    raw = re.sub(r"^```[a-z]*\n?", "", raw)
                    raw = re.sub(r"\n?```$", "", raw).strip()

                if not raw:
                    STATS["retries"] += 1
                    continue

                data = json.loads(raw)
                return data, model, tokens, cost

            except json.JSONDecodeError:
                STATS["retries"] += 1
                log.debug(f"    bad JSON from {model} (attempt {attempt + 1})")
                time.sleep(0.3)

            except Exception as exc:
                msg = str(exc)
                STATS["retries"] += 1
                log.debug(f"    {model} error: {msg[:80]}")
                if "rate" in msg.lower() or "429" in msg:
                    break  # rate-limited — move to next model
                time.sleep(0.5)

    return None, None, 0, 0.0


# ═══════════════════════════════════════════════════════════════════════════
#  DOCUMENT DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════════

DOCUMENT_EXTENSIONS = {
    ".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".rar", ".7z",
    ".odt", ".ods", ".p7s", ".gaeb", ".x81", ".x83", ".d83", ".d84",
}

# Keywords in link text that strongly suggest a tender document
DOC_TEXT_KEYWORDS = [
    "unterlag", "leistungsverzeichnis", "leistungsbeschreibung",
    "ausschreibung", "vergabeunterlag", "angebotsunterlag",
    "teilnahmeunterlag", "lv ", "gaeb", "formular", "bewerbungsbogen",
    "eignungsnachweis", "auftragsbekanntmachung", "bekanntmachung",
    "vertragsbedingung", "leistungsheft", "baubeschreibung",
    "planunterlag", "herunterladen", "download", "dokument",
    "zip herunterladen", "als zip", "unterlagen herunterladen",
    "alle dokumente", "bieterunterlagen",
]

# Link text that means "skip — not a document"
DOC_SKIP_TEXT = [
    "agb", "datenschutz", "impressum", "nutzungsbedingung",
    "hilfe", "handbuch", "anleitung", "tutorial", "newsletter",
    "broschüre", "flyer", "logo", "registrierung", "anmelden",
    "login", "startseite", "home", "zurück", "weiter",
    "mehr erfahren", "read more", "alle ausschreibungen",
    "suche", "merkliste", "favoriten", "cookie", "sprachauswahl",
]

# URL paths that mean "skip"
DOC_SKIP_URL = [
    "/agb", "/datenschutz", "/impressum", "/hilfe", "/help",
    "/login", "/register", "/auth", "/account",
    "/news/", "/blog/", "/presse/", "/aktuell",
    ".css", ".js", ".png", ".jpg", ".gif", ".svg",
    ".ico", ".woff", ".ttf", ".eot",
]

# URL keywords (weaker signal than link text)
DOC_URL_KEYWORDS = [
    "unterlag", "leistung", "vergabe", "gaeb", "dokument",
    "formular", "ausschreibung", "download", "attachment", "file",
    "bieter", "angebot", "tender",
]

# XPaths for hidden document sections behind tabs / accordions
REVEAL_BUTTON_XPATHS = [
    "//button[contains(.,'Vergabeunterlagen')]",
    "//button[contains(.,'Unterlagen')]",
    "//button[contains(.,'Dokumente')]",
    "//a[contains(@class,'tab') and contains(.,'Unterlagen')]",
    "//a[contains(@class,'tab') and contains(.,'Dokumente')]",
    "//li[contains(@class,'tab') and contains(.,'Unterlagen')]",
    "//div[contains(@class,'tab') and contains(.,'Unterlagen')]",
    "//button[contains(.,'Dokumente anzeigen')]",
    "//button[contains(.,'Unterlagen anzeigen')]",
    "//button[contains(.,'Unterlagen herunterladen')]",
    "//div[contains(@class,'accordion') and contains(.,'Unterlagen')]//button",
    "//div[contains(@class,'collapse') and contains(.,'Dokumente')]//button",
    "//a[@id='documents-tab']",
    "//a[@href='#documents']",
    "//a[@href='#unterlagen']",
    "//button[@data-target='#documents']",
    "//button[@data-target='#unterlagen']",
    "//button[contains(text(),'Unterlagen')]",
    "//div[contains(@class,'dashboard')]//a[contains(.,'Unterlagen')]",
    "//a[contains(@class,'BekSummary')]",
    "//div[contains(@class,'dx-tab')]//span[contains(text(),'Dokumente')]",
    "//div[contains(@class,'dx-tab')]//span[contains(text(),'Unterlagen')]",
    "//a[contains(text(),'bitte hier klicken')]",
]


def score_doc_link(href: str, link_text: str, page_domain: str) -> int:
    """
    Rate how likely a link is to be a tender document (0–3).
      0 = skip,  1 = possible,  2 = likely,  3 = definite
    """
    lower_href = href.lower()
    lower_text = (link_text or "").strip().lower()
    path = urlparse(href).path.lower()
    link_domain = urlparse(href).netloc.lower()

    # Cross-domain links are almost never tender docs
    if link_domain and link_domain != page_domain:
        known_doc_domains = ["evergabe", "vergabe", "subreport", "had.de", "tender24", "ausschreibungsblatt", "bi-medien"]
        if not any(x in link_domain for x in known_doc_domains):
            return 0

    if any(k in lower_href for k in DOC_SKIP_URL):
        return 0
    if any(k in lower_text for k in DOC_SKIP_TEXT):
        return 0

    ext = Path(path).suffix.lower()
    has_doc_ext     = ext in DOCUMENT_EXTENSIONS
    has_strong_text = any(k in lower_text for k in DOC_TEXT_KEYWORDS)
    has_url_hint    = any(k in lower_href for k in DOC_URL_KEYWORDS)

    if not has_doc_ext and not has_strong_text and not has_url_hint:
        return 0

    score = 0
    if has_doc_ext:
        score += 1
    if has_strong_text:
        score += 2
    elif has_url_hint:
        score += 1

    return min(score, 3)


async def collect_doc_links(page, base_url: str) -> List[Tuple[str, str, int]]:
    """Scan the page for candidate document links, scored and sorted best-first."""
    page_domain = urlparse(base_url).netloc.lower()
    candidates = []
    seen = set()

    # Scan <a> tags
    try:
        for link in await page.locator("xpath=//a[@href]").all():
            try:
                href = await link.get_attribute("href")
                if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                full_url = urljoin(base_url, href)
                if full_url in seen:
                    continue
                seen.add(full_url)

                text = (await link.inner_text()).strip()
                sc = score_doc_link(full_url, text, page_domain)

                # Special case: evergabe portals sometimes hide docs in API paths
                if "evergabe" in page_domain and sc == 0:
                    if "document" in full_url or "/api/file/" in full_url or "download" in full_url:
                        sc = 2

                if sc > 0:
                    candidates.append((full_url, text, sc))
            except Exception:
                pass
    except Exception:
        pass

    # Scan <form> tags with download-like actions
    try:
        forms = await page.locator("xpath=//form[contains(@action,'download') or contains(@action,'unterlag')]").all()
        for form in forms:
            try:
                action = await form.get_attribute("action")
                if action:
                    full = urljoin(base_url, action)
                    if full not in seen:
                        seen.add(full)
                        candidates.append((full, "form-download", 2))
            except Exception:
                pass
    except Exception:
        pass

    candidates.sort(key=lambda x: -x[2])
    return candidates


async def click_reveal_buttons(page) -> bool:
    """Click tabs / accordions that might reveal hidden document sections."""
    clicked = False
    for xp in REVEAL_BUTTON_XPATHS:
        try:
            el = page.locator(f"xpath={xp}").first
            if await el.is_visible(timeout=400):
                await el.click()
                await page.wait_for_timeout(800)
                clicked = True
        except Exception:
            pass

    # Also try data-attribute based tabs via JS
    try:
        await page.evaluate("""
            document.querySelectorAll(
                '[data-tab="documents"],[data-tab="unterlagen"],'
                + '[href="#documents"],[href="#unterlagen"]'
            ).forEach(el => { try { el.click(); } catch(e) {} });
        """)
        await page.wait_for_timeout(500)
    except Exception:
        pass

    return clicked


async def fetch_single_doc(page, download_url: str, base_url: str, folder: str,
                           saved_count: int, max_docs: int,
                           content_hashes: set) -> Optional[str]:
    """Download one file and save it. Returns the filename, or None on failure."""
    if saved_count >= max_docs:
        return None

    try:
        response = await page.context.request.get(
            download_url,
            timeout=25000,
            headers={
                "Accept": "application/pdf,application/zip,application/octet-stream,*/*;q=0.8",
                "Referer": base_url,
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                "Cache-Control": "no-cache",
            },
        )

        if response.status >= 400:
            return None

        content_type = response.headers.get("content-type", "").lower()
        if "text/html" in content_type:
            return None

        body = await response.body()
        if len(body) < 300:
            return None

        # De-duplicate by content hash
        content_hash = hashlib.md5(body[:4096]).hexdigest()
        if content_hash in content_hashes:
            log.debug("    dup skipped (same content hash)")
            return None
        content_hashes.add(content_hash)

        # Figure out a good filename
        cd = response.headers.get("content-disposition", "")
        filename = ""

        m = re.search(r"filename\*=(?:[Uu][Tt][Ff]-8'')?([^\s;]+)", cd)
        if m:
            filename = unquote(m.group(1))
        if not filename:
            m = re.search(r'filename=["\']?([^"\';\r\n]+)', cd)
            if m:
                filename = m.group(1).strip("\"' ")
        if not filename:
            url_path = urlparse(download_url).path
            filename = unquote(url_path.split("/")[-1].split("?")[0])

        generic_names = {"download", "document", "file", "attachment", "", "get"}
        if filename.lower() in generic_names or not filename:
            ext_map = {
                "pdf": "pdf", "zip": "zip", "msword": "doc",
                "vnd.openxmlformats-officedocument.wordprocessingml": "docx",
                "vnd.ms-excel": "xls",
                "vnd.openxmlformats-officedocument.spreadsheetml": "xlsx",
                "x-gaeb": "x83",
            }
            ext = "bin"
            for key, value in ext_map.items():
                if key in content_type:
                    ext = value
                    break
            filename = f"doc_{saved_count + 1}_{content_hash[:6]}.{ext}"

        filename = re.sub(r"[^\w.\-]", "_", filename)[:120]
        dest = os.path.join(folder, filename)

        if os.path.exists(dest):
            return filename

        with open(dest, "wb") as fh:
            fh.write(body)

        size_kb = len(body) // 1024
        log.info(f"    ↓ {filename}  ({size_kb}KB)  [{content_type.split(';')[0]}]")
        return filename

    except Exception as exc:
        log.debug(f"    fetch failed {download_url[:80]}: {str(exc)[:80]}")
        return None


async def try_js_download_buttons(page, base_url: str, folder: str,
                                  saved_count: int, max_docs: int,
                                  content_hashes: set) -> List[str]:
    """Click JS-powered download buttons and intercept the resulting requests."""
    saved = []
    btn_xpaths = [
        "//button[contains(.,'Unterlagen herunterladen')]",
        "//button[contains(.,'Alle Unterlagen')]",
        "//button[contains(.,'ZIP herunterladen')]",
        "//button[contains(.,'Dokumente herunterladen')]",
        "//a[contains(@class,'download') and contains(.,'Unterlagen')]",
        "//a[contains(@class,'zipDownload')]",
        "//button[contains(@class,'download')]",
    ]
    intercepted_urls = []

    async def on_request(req):
        url_lower = req.url.lower()
        if any(ext in url_lower for ext in [".pdf", ".zip", ".docx", ".doc", "download", "attachment"]):
            intercepted_urls.append(req.url)

    page.on("request", on_request)
    for xp in btn_xpaths:
        try:
            btn = page.locator(f"xpath={xp}").first
            if await btn.is_visible(timeout=400):
                await btn.click()
                await page.wait_for_timeout(1500)
        except Exception:
            pass
    page.remove_listener("request", on_request)

    for url in intercepted_urls:
        if len(saved) + saved_count >= max_docs:
            break
        fn = await fetch_single_doc(page, url, base_url, folder,
                                    len(saved) + saved_count, max_docs, content_hashes)
        if fn:
            saved.append(fn)
    return saved


def _sanitise_path(s: str, maxlen: int = 80) -> str:
    """Turn an arbitrary string into something safe for a folder name."""
    s = str(s).strip()
    s = re.sub(r'[\\/:"*?<>|]', "", s)
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^\w\-]", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:maxlen] or "unknown"


def make_download_folder(download_dir: str, tender_id: str,
                         authority: Optional[str], folder_by_company: bool) -> str:
    """Build the output folder path for a tender's documents."""
    tid_safe = _sanitise_path(tender_id, 60)
    if folder_by_company and authority:
        company_safe = _sanitise_path(authority, 80)
        return os.path.join(download_dir, company_safe, tid_safe)
    return os.path.join(download_dir, tid_safe)


async def download_documents(page, tender_id: str, base_url: str,
                             download_dir: str, max_docs: int = 15,
                             authority: str = None,
                             folder_by_company: bool = False) -> List[str]:
    """
    Multi-pass document download strategy:
      Pass 1 — score all links on the page
      Pass 2 — click reveal buttons, re-scan if few strong links found
      Pass 3 — try JS download buttons
      Pass 4 — portal-specific API patterns
      Pass 5 — download scored links (strong first, weak as fallback)
    """
    saved = []
    folder = make_download_folder(download_dir, tender_id, authority, folder_by_company)
    os.makedirs(folder, exist_ok=True)
    attempted = set()
    content_hashes = set()

    # Pass 1: score all links on the current page
    candidates = await collect_doc_links(page, base_url)

    # Pass 2: click reveal buttons if few strong links found
    strong = [c for c in candidates if c[2] >= 2]
    if len(strong) < 2:
        if await click_reveal_buttons(page):
            await page.wait_for_timeout(1000)
            candidates = await collect_doc_links(page, base_url)
            strong = [c for c in candidates if c[2] >= 2]

    # Pass 3: try JS download buttons
    if not saved:
        js_docs = await try_js_download_buttons(page, base_url, folder,
                                                len(saved), max_docs, content_hashes)
        saved.extend(js_docs)

    # Pass 4: portal-specific API patterns
    parsed = urlparse(base_url)
    netloc = parsed.netloc.lower()
    portal_urls = []

    if "evergabe" in netloc or "auftraege.bayern.de" in netloc:
        m_oid = re.search(r"/tenders?/(\d+)", parsed.path)
        m_sid = re.search(r"([0-9a-f-]{36}|[A-Za-z0-9+/]{10,50}={0,2})", parsed.path + parsed.query)
        m_sid_q = re.search(r"subProjectId=([^&]+)", parsed.query)

        sid = None
        if m_sid_q:
            sid = m_sid_q.group(1)
        elif m_sid:
            sid = m_sid.group(1)

        base = f"{parsed.scheme}://{parsed.netloc}"
        if m_oid:
            portal_urls.append(f"{base}/tender/{m_oid.group(1)}/documents")
            portal_urls.append(f"{base}/tender/{m_oid.group(1)}/documents/download")
        if sid and len(sid) > 10:
            if "auftraege.bayern.de" in netloc:
                portal_urls.append(f"https://www.auftraege.bayern.de/evergabe.bieter/DownloadTenderFiles.ashx?subProjectId={sid}")
                portal_urls.append(f"https://bieterzugang.auftraege.bayern.de/evergabe.bieter/DownloadTenderFiles.ashx?subProjectId={sid}")
            else:
                portal_urls.append(f"https://bieterzugang.deutsche-evergabe.de/evergabe.bieter/DownloadTenderFiles.ashx?subProjectId={sid}")
                portal_urls.append(f"https://www.deutsche-evergabe.de/dashboards/DetailsDashboard/{sid}")

    if "subreport" in netloc:
        m = re.search(r"[?&]id=(\d+)", parsed.query + "?" + parsed.path)
        if m:
            base = f"{parsed.scheme}://{parsed.netloc}"
            portal_urls.append(f"{base}/dokumente.aspx?id={m.group(1)}")

    if "vergabe24" in netloc or "tender24" in netloc:
        m_tid = re.search(r"(54321-Tender-[a-f0-9-]+)", base_url)
        if m_tid:
            tid = m_tid.group(1)
            base = f"{parsed.scheme}://{parsed.netloc}"
            portal_urls.append(f"{base}/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}&view=documents")

        m_tok = re.search(r"token=([a-zA-Z0-9_-]+)", base_url)
        if m_tok:
            tok = m_tok.group(1)
            base = f"{parsed.scheme}://{parsed.netloc}"
            portal_urls.append(f"{base}/download.php?token={tok}")

    for pu in portal_urls:
        if pu not in attempted and len(saved) < max_docs:
            attempted.add(pu)
            fn = await fetch_single_doc(page, pu, base_url, folder,
                                        len(saved), max_docs, content_hashes)
            if fn:
                saved.append(fn)

    # Pass 5: download scored links
    threshold = 2 if (strong or saved) else 1
    for doc_url, text, score in candidates:
        if len(saved) >= max_docs:
            break
        if score < threshold or doc_url in attempted:
            continue
        attempted.add(doc_url)
        fn = await fetch_single_doc(page, doc_url, base_url, folder,
                                    len(saved), max_docs, content_hashes)
        if fn:
            saved.append(fn)

    if not saved:
        log.debug(f"    no docs found: {base_url[:60]}")

    return saved


# ═══════════════════════════════════════════════════════════════════════════
#  URL SKIP PATTERNS
# ═══════════════════════════════════════════════════════════════════════════

SKIP_URL_PATTERNS = [
    "/login", "/register", "/auth",
    "/passwort", "/password", "/account", "/warenkorb", "/cart",
    "/impressum", "/datenschutz", "/agb", "/hilfe",
    "zustellweg",
]


def should_skip_url(url: str) -> bool:
    """Return True if the URL is clearly not a tender detail page."""
    low = url.lower()
    if "zustellweg" in low:
        return True
    if re.search(r"/unterlagen/[0-9a-f-]{36}/zustellweg", low):
        return True
    return any(p in low for p in SKIP_URL_PATTERNS)


# ═══════════════════════════════════════════════════════════════════════════
#  SCRAPE ONE URL
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_one(page, row: dict, client=None, use_llm: bool = False,
                     download_docs: bool = False, download_dir: str = "downloads",
                     folder_by_company: bool = False) -> dict:
    """Scrape a single tender URL and return a result dict."""
    url = row.get("url", "").strip()
    domain = urlparse(url).netloc.lower()
    result = empty_result(row, domain)
    t0 = time.time()

    try:
        if should_skip_url(url):
            result["status"] = "invalid"
            result["err"] = "non-tender URL (delivery/login page)"
            return result

        # Load the page (with full recovery chain)
        page_text, used_url, recovery = await load_with_recovery(page, row)
        result["url_used"] = used_url
        result["url_recovery"] = recovery

        if recovery:
            STATS["url_recoveries"].setdefault(recovery, 0)
            STATS["url_recoveries"][recovery] += 1
            log.info(f"    🔄 URL recovered via {recovery}: {used_url[:70]}")

        if not page_text or len(page_text) < 50:
            result["status"] = "error"
            result["err"] = "empty page after all recovery attempts"
            return result

        # Extraction
        try:
            if use_llm and client:
                data, model_used, tok, cost = extract_with_llm(client, page_text, used_url, domain)
                result["model_used"] = model_used
                result["llm_tokens"] = tok
                result["llm_cost"] = cost

                if data:
                    for field in ("title", "authority", "description", "deadline",
                                  "pub_date", "proc_type", "cpv", "location",
                                  "ref_num", "contact"):
                        result[field] = data.get(field)

                # If LLM returned nothing useful, fall back to XPath
                if not result["title"] and not result["authority"]:
                    xpath_data = await xpath_extract(page)
                    for k, v in xpath_data.items():
                        if not result.get(k):
                            result[k] = v
                    if result["title"] or result["authority"]:
                        result["model_used"] = "xpath_fallback"
            else:
                # Phase 1: pure XPath
                xpath_data = await xpath_extract(page)
                for k, v in xpath_data.items():
                    result[k] = v

        except Exception as exc:
            if "closed" not in str(exc).lower():
                log.debug(f"    extraction failed: {exc}")

        # Status
        if result["title"] or result["authority"]:
            result["status"] = "success"
        else:
            result["status"] = "error"
            result["err"] = "nothing extracted"

        # Document download (only for successful extractions)
        if download_docs and result["status"] == "success":
            try:
                tender_id = result["id"] or re.sub(r"[^\w]", "_", used_url[-40:])
                docs = await download_documents(
                    page, tender_id, used_url, download_dir,
                    authority=result.get("authority"),
                    folder_by_company=folder_by_company,
                )
                result["downloaded_docs"] = docs
                if docs:
                    log.info(f"    saved {len(docs)} doc(s) for {str(tender_id)[:20]}")
            except Exception as exc:
                log.debug(f"    downloads failed: {exc}")
                result["err"] = f"downloads: {str(exc)[:100]}"

    except Exception as exc:
        result["status"] = "error"
        result["err"] = str(exc)[:300]
        if "closed" not in str(exc).lower():
            log.error(f"    !!! error on {url[:60]}: {exc}")

    result["ms"] = int((time.time() - t0) * 1000)
    result["ts"] = datetime.now().isoformat()
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  BATCH RUNNER — one browser tab per domain
# ═══════════════════════════════════════════════════════════════════════════

async def run_domain(domain: str, rows: list, results: list,
                     sem: asyncio.Semaphore, ctx, prog: dict, total: int,
                     client, use_llm: bool, download_docs: bool,
                     download_dir: str, folder_by_company: bool = False):
    """Process all URLs for a single domain in one persistent browser tab."""
    log.info(f"  {domain}  ({len(rows)} urls)")
    page = await ctx.new_page()

    for row in rows:
        async with sem:
            if page.is_closed():
                try:
                    page = await ctx.new_page()
                except Exception:
                    pass

            rec = await scrape_one(
                page, row, client=client, use_llm=use_llm,
                download_docs=download_docs, download_dir=download_dir,
                folder_by_company=folder_by_company,
            )
            results.append(rec)

            prog["n"] += 1
            n = prog["n"]
            icon = {"success": "✓", "timeout": "⏱"}.get(rec["status"], "✗")
            recovery_label = f" [{rec['url_recovery']}]" if rec.get("url_recovery") else ""
            model_label = f" [{rec['model_used']}]" if rec.get("model_used") else ""
            log.info(
                f"  {icon} [{n}/{total} {100 * n / total:.1f}%] "
                f"{domain} {rec['status']} {rec['ms']}ms{model_label}{recovery_label}"
            )

    try:
        if not page.is_closed():
            await page.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  SAVING RESULTS
# ═══════════════════════════════════════════════════════════════════════════

CSV_COLUMNS = [
    "id", "url", "url_used", "domain", "status",
    "title", "authority", "description", "deadline", "pub_date",
    "proc_type", "cpv", "location", "ref_num", "contact",
    "model_used", "llm_tokens", "llm_cost",
    "downloaded_docs", "url_recovery", "err", "ms", "ts",
