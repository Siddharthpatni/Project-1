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
