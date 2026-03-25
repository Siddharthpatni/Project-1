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
