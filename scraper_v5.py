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
