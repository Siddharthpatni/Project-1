"""
vergabe24_recovery.py  –  Recover expired vergabe24 URLs via search
======================================================================
If the original URL in the dataset is expired (ERR_HTTP2_PROTOCOL_ERROR),
we extract the Tender ID and search for the active URL on DuckDuckGo/Google.

Strategies in order:
  1. Construct NetServer URLs directly (same backend, alternative URL)
  2. DuckDuckGo Search: site:vergabe24.de "54321-Tender-XXXXX"
  3. Google Search (fallback if DDG finds nothing)

Installation:
    pip install requests

Test Run:
    python vergabe24_recovery.py
    python vergabe24_recovery.py "https://www.vergabe24.de/vergabeunterlagen/54321-Tender-XXX"
"""

import re
import time
import logging
import requests
from urllib.parse import urlparse, quote_plus
from typing import Optional

log = logging.getLogger("s")

# ---------------------------------------------------------------------------
# EXTRACT TENDER ID FROM URL
# ---------------------------------------------------------------------------

def extract_tender_id(url: str) -> Optional[str]:
    """
    Extracts the tender ID from any vergabe24 URL format.
    
    Examples:
      /vergabeunterlagen/54321-Tender-19cdd4f196f-55ed433e45a54a4a  → 54321-Tender-19cdd4f196f-55ed433e45a54a4a
      /NetServer/TenderingProcedureDetails?TenderOID=54321-Tender-XX  → 54321-Tender-XX
    """
    # Main format: 54321-Tender-HEXHEX
    m = re.search(r'(54321-(?:Tender|PublishingProcess)-[a-f0-9][a-f0-9\-]+)', url, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# STRATEGY 1: ALTERNATIVE NETSERVER URLS (headless/no browser)
# ---------------------------------------------------------------------------

NETSERVER_PATTERNS = [
    # These URLs use the same backend but don't expire as quickly
    "https://www.vergabe24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
    "https://www.vergabe24.de/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0",
    "https://europa.vergabe24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
    "https://europa.vergabe24.de/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0",
    # tender24.de – same system, different domain
    "https://www.tender24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
]

def try_netserver_urls(tender_id: str, timeout: int = 10) -> Optional[str]:
    """
    Tries the NetServer URLs directly using requests (without a browser).
    Returns the first URL that responds with a 200 OK and contains tender data.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }

    for pattern in NETSERVER_PATTERNS:
        url = pattern.format(tid=tender_id)
        try:
            resp = requests.get(url, headers=headers, timeout=timeout,
                                allow_redirects=True)
            if resp.status_code == 200 and len(resp.text) > 500:
                # Check that the page contains actual data (not an error page)
                text_lower = resp.text.lower()
                has_content = any(kw in text_lower for kw in [
                    "auftraggeber", "vergabe", "leistung", "frist",
                    "bekanntmachung", tender_id.lower()
                ])
                if has_content:
                    log.info(f"  [recovery] NetServer URL works: {url}")
                    return url
                else:
                    log.debug(f"  [recovery] {url} → 200 but lacks relevant content")
            else:
                log.debug(f"  [recovery] {url} → {resp.status_code}")
        except Exception as e:
            log.debug(f"  [recovery] {url} → error: {str(e)[:60]}")

    return None


# ---------------------------------------------------------------------------
# STRATEGY 2 & 3: WEB SEARCH (DuckDuckGo + Google)
# ---------------------------------------------------------------------------

def search_duckduckgo(tender_id: str, timeout: int = 10) -> Optional[str]:
    """
    Searches for the tender ID on DuckDuckGo and returns the first vergabe24 URL found.
    Uses the DDG HTML API (does not require a browser).
    """
    query = f'"{tender_id}"'
    url   = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9",
        "Accept": "text/html,*/*",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            log.debug(f"  [DDG] status {resp.status_code}")
            return None

        # Extract links from HTML results
        links = re.findall(r'href="(https?://[^"]+)"', resp.text)
        for link in links:
            parsed = urlparse(link)
            netloc = parsed.netloc.lower()
            if ("vergabe24" in netloc or "tender24" in netloc):
                # Exclude search engine/navigation links
                if any(skip in link for skip in ["duckduckgo", "google", "bing", "/search"]):
                    continue
                log.info(f"  [DDG] found: {link}")
                return link

    except Exception as e:
        log.debug(f"  [DDG] error: {str(e)[:80]}")

    return None


def search_google(tender_id: str, timeout: int = 10) -> Optional[str]:
    """
    Searches for the tender ID on Google and returns the first vergabe24 URL found.
    Note: Google may block automated requests; DDG is more reliable.
    """
    query = f'site:vergabe24.de OR site:tender24.de "{tender_id}"'
    url   = f"https://www.google.com/search?q={quote_plus(query)}&num=5"

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "de-DE,de;q=0.9",
        "Accept": "text/html,*/*",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            log.debug(f"  [Google] status {resp.status_code}")
            return None

        # Google hides real URLs inside /url?q= or exposes them directly
        # Try both patterns
        patterns = [
            r'/url\?q=(https?://(?:www\.|europa\.)?(?:vergabe24|tender24)\.de[^&"]+)',
            r'href="(https?://(?:www\.|europa\.)?(?:vergabe24|tender24)\.de[^"]+)"',
        ]
        for pat in patterns:
            matches = re.findall(pat, resp.text)
            for match in matches:
                from urllib.parse import unquote
                clean = unquote(match)
                if tender_id.lower() in clean.lower():
                    log.info(f"  [Google] found: {clean}")
                    return clean

    except Exception as e:
        log.debug(f"  [Google] error: {str(e)[:80]}")

    return None

def recover_vergabe24_url(original_url: str) -> dict:

    result = {
        "tender_id":    None,
        "original_url": original_url,
        "found_url":    None,
        "strategy":     None,
        "download_url": None,
    }

    # Tender ID
    tender_id = extract_tender_id(original_url)
    if not tender_id:
        log.warning(f"  [recovery] cannot extract Tender ID from: {original_url}")
        return result

    result["tender_id"] = tender_id
    log.info(f"  [recovery] Tender ID: {tender_id}")

    # ── Strategy 1: Alternative NetServer URLs ─────────────────────────
    log.info("  [recovery] trying NetServer URLs...")
    found = try_netserver_urls(tender_id)
    if found:
        result["found_url"] = found
        result["strategy"]  = "netserver"
        return result

    # ── Strategy 2: DuckDuckGo ────────────────────────────────────────────
    log.info("  [recovery] trying DuckDuckGo...")
    found = search_duckduckgo(tender_id)
    if found:
        result["found_url"] = found
        result["strategy"]  = "duckduckgo"
        return result

    # ── Strategy 3: Google ────────────────────────────────────────────────
    log.info("  [recovery] trying Google...")
    found = search_google(tender_id)
    if found:
        result["found_url"] = found
        result["strategy"]  = "google"
        return result

    log.warning(f"  [recovery] tender {tender_id} was not found via any strategy")
    return result


# ---------------------------------------------------------------------------
# INTEGRATION WITH SCRAPER_V4.PY
# ---------------------------------------------------------------------------
# Add in load_with_recovery(), before Strategy 0:
#
#   from vergabe24_recovery import recover_vergabe24_url, extract_tender_id
#
#   if "vergabe24" in domain or "tender24" in domain:
#       recovery = recover_vergabe24_url(original_url)
#       if recovery["found_url"]:
#           # replace the row URL with the recovered one
#           row["url"] = recovery["found_url"]
#           log.info(f"  URL recovered via {recovery['strategy']}: {recovery['found_url']}")
#           # continue normal scraping with the new URL


# ---------------------------------------------------------------------------
# STANDALONE TEST
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s  %(message)s",
    )

    test_url = (
        sys.argv[1] if len(sys.argv) > 1
        else "https://www.vergabe24.de/vergabeunterlagen/54321-Tender-19cdd4f196f-55ed433e45a54a4a"
    )

    print(f"\n{'='*65}")
    print(f"  RECOVERY TEST")
    print(f"  Original URL: {test_url}")
    print(f"{'='*65}\n")

    result = recover_vergabe24_url(test_url)

    print(f"\n{'='*65}")
    print(f"  Tender ID:  {result['tender_id']}")
    if result["found_url"]:
        print(f"  ✓ URL found: {result['found_url']}")
        print(f"  Strategy:    {result['strategy']}")
    else:
        print(f"  ✗ No active URL found.")
        print(f"  → The tender is likely deleted or archived.")
    print(f"{'='*65}\n")