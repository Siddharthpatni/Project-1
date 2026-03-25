#!/usr/bin/env python3
"""
scraper.py — German public procurement tender scraper
======================================================

3-layer hybrid architecture:
  Layer 1 (FAST)      — XPath / CSS selectors for known portal patterns
  Layer 2 (HEURISTIC) — keyword-scored link scanning + reveal-button clicks
  Layer 3 (AGENT)     — CUA agent via OpenRouter (only when layers 1-2 fail)

Also includes:
  • vergabe24 / tender24 URL recovery (NetServer → DDG → Google)
  • Cookie-banner dismissal (German + English variants)
  • Content-hash deduplication for downloads
  • Per-domain tab reuse for efficiency
  • JSON + CSV result output with full stats summary
  • CLI flags for limit, workers, LLM toggle, download toggle

Usage:
    # Fast XPath-only pass
    python scraper.py -i publications_b.csv -n 50

    # With LLM extraction fallback
    python scraper.py -i publications_b.csv --llm --api-key YOUR_KEY

    # Full run with document downloads
    python scraper.py -i publications_b.csv --llm --download-docs

Requirements:
    pip install playwright openai python-dotenv requests
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
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# ── encoding fix for Windows terminals ────────────────────────────────────
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── env ───────────────────────────────────────────────────────────────────
load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# ── logging ───────────────────────────────────────────────────────────────
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

MAX_CONCURRENT    = 8          # parallel browser tabs
DOWNLOAD_DIR      = "downloads"
TIMEOUT_PAGE      = 20_000     # ms — page load
TIMEOUT_DOWNLOAD  = 25_000     # ms — file fetch
MAX_DOCS_PER_URL  = 15

# LLM model chain — cheapest first
MODEL_CHAIN = [
    "google/gemini-2.5-flash-lite",
    "qwen/qwen3-14b",
]

# Run-wide statistics
STATS = {
    "total":            0,
    "fast_success":     0,
    "heuristic_success":0,
    "agent_success":    0,
    "failed":           0,
    "error":            0,
    "llm_calls":        0,
    "llm_tokens":       0,
    "llm_cost":         0.0,
    "url_recoveries":   {},
}


# ═══════════════════════════════════════════════════════════════════════════
#  RESULT SCHEMA
# ═══════════════════════════════════════════════════════════════════════════

def empty_result(row: dict, domain: str) -> dict:
    return {
        "id":               row.get("id", ""),
        "url":              row.get("url", ""),
        "url_used":         None,
        "domain":           domain,
        "status":           "pending",
        "layer":            None,
        "title":            None,
        "authority":        None,
        "description":      None,
        "deadline":         None,
        "pub_date":         None,
        "proc_type":        None,
        "cpv":              None,
        "location":         None,
        "ref_num":          None,
        "contact":          None,
        "model_used":       None,
        "llm_tokens":       0,
        "llm_cost":         0.0,
        "downloaded_docs":  [],
        "url_recovery":     None,
        "err":              None,
        "ms":               0,
        "ts":               "",
    }


# ═══════════════════════════════════════════════════════════════════════════
#  COOKIE BANNER DISMISSAL
# ═══════════════════════════════════════════════════════════════════════════

_COOKIE_SELECTORS = [
    "xpath=//button[contains(text(),'Akzeptieren')]",
    "xpath=//button[contains(text(),'Alle akzeptieren')]",
    "xpath=//button[contains(text(),'Annehmen')]",
    "xpath=//button[contains(text(),'Zustimmen')]",
    "xpath=//button[contains(text(),'Einverstanden')]",
    "xpath=//button[contains(text(),'Nur notwendige')]",
    "xpath=//button[contains(text(),'Accept')]",
    "xpath=//button[contains(text(),'Accept all')]",
    "xpath=//button[contains(@class,'accept') or contains(@class,'consent')]",
    "xpath=//button[@id='accept' or @id='acceptCookies' or @id='cookieAccept']",
    "xpath=//a[contains(text(),'Akzeptieren') or contains(text(),'Accept')]",
]


async def dismiss_cookies(page) -> bool:
    for sel in _COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=400):
                await btn.click()
                await page.wait_for_timeout(400)
                return True
        except Exception:
            pass
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  VERGABE24 URL RECOVERY  (ported from v5)
# ═══════════════════════════════════════════════════════════════════════════

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
}

_NETSERVER_TEMPLATES = [
    "https://www.vergabe24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
    "https://www.vergabe24.de/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0",
    "https://europa.vergabe24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
    "https://europa.vergabe24.de/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0",
    "https://www.tender24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
]

_TENDER_CONTENT_KW = ["auftraggeber", "vergabe", "leistung", "frist", "bekanntmachung"]


def _extract_tender_id(url: str) -> Optional[str]:
    m = re.search(r"(54321-(?:Tender|PublishingProcess)-[a-f0-9][a-f0-9\-]+)", url, re.IGNORECASE)
    return m.group(1) if m else None


def _try_netserver(tid: str) -> Optional[str]:
    for tmpl in _NETSERVER_TEMPLATES:
        url = tmpl.format(tid=tid)
        try:
            r = requests.get(url, headers=_BROWSER_HEADERS, timeout=10, allow_redirects=True)
            if r.status_code != 200 or len(r.text) < 500:
                continue
            body = r.text.lower()
            if any(kw in body for kw in _TENDER_CONTENT_KW) or tid.lower() in body:
                return url
        except Exception:
            pass
    return None


def _search_ddg(tid: str) -> Optional[str]:
    try:
        r = requests.get(
            f"https://html.duckduckgo.com/html/?q={quote_plus(tid)}",
            headers=_BROWSER_HEADERS, timeout=10,
        )
        for href in re.findall(r'href="(https?://[^"]+)"', r.text):
            netloc = urlparse(href).netloc.lower()
            if ("vergabe24" in netloc or "tender24" in netloc) and "duckduckgo" not in href:
                return href
    except Exception:
        pass
    return None


def recover_vergabe24_url(original_url: str) -> dict:
    """Try multiple strategies to find a working replacement for an expired vergabe24 URL."""
    result = {"tender_id": None, "original_url": original_url, "found_url": None, "strategy": None}
    tid = _extract_tender_id(original_url)
    if not tid:
        return result
    result["tender_id"] = tid

    found = _try_netserver(tid)
    if found:
        result.update(found_url=found, strategy="netserver")
        return result

    found = _search_ddg(tid)
    if found:
        result.update(found_url=found, strategy="duckduckgo")
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  URL NORMALISATION
# ═══════════════════════════════════════════════════════════════════════════

def fix_double_encoding(url: str) -> str:
    return re.sub(r"%25([0-9A-Fa-f]{2})", r"%\1", url)


def strip_documents_suffix(url: str) -> Optional[str]:
    clean = re.sub(r"/documents/?$", "", url, flags=re.IGNORECASE)
    return clean if clean != url else None


# ═══════════════════════════════════════════════════════════════════════════
#  PAGE CLASSIFICATION
# ═══════════════════════════════════════════════════════════════════════════

_LOGIN_PHRASES = [
    "bitte melden sie sich an", "please log in", "login required",
    "session abgelaufen", "session expired", "zugangsdaten", "403 forbidden",
    "zugang verweigert", "sie sind nicht eingeloggt",
]
_GONE_PHRASES = [
    "nicht mehr verfügbar", "nicht gefunden", "abgelaufen",
    "page not found", "vergabe wurde aufgehoben", "404", "403 forbidden",
    "diese ausschreibung existiert nicht",
]


def _is_login_wall(text: str) -> bool:
    s = text.lower()[:3000]
    return any(p in s for p in _LOGIN_PHRASES)


def _is_gone(text: str) -> bool:
    s = text.lower()[:6000]
    return any(p in s for p in _GONE_PHRASES)


# ═══════════════════════════════════════════════════════════════════════════
#  PAGE TEXT
# ═══════════════════════════════════════════════════════════════════════════

async def get_page_text(page, max_chars: int = 8000) -> str:
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
    if len(text) < 100:
        await page.wait_for_timeout(2000)
        try:
            text = await page.inner_text("body")
            text = re.sub(r"\n{3,}", "\n\n", text).strip()
        except Exception:
            pass
    return text[:max_chars]


# ═══════════════════════════════════════════════════════════════════════════
#  PAGE LOADING WITH RECOVERY
# ═══════════════════════════════════════════════════════════════════════════

async def load_with_recovery(page, url: str) -> Tuple[str, str, Optional[str]]:
    """
    Load a tender page, cycling through fallback strategies on failure.
    Returns (page_text, final_url, recovery_label_or_None).
    """
    url = fix_double_encoding(url.strip())

    async def _try(target_url: str, label: str) -> Optional[Tuple[str, str]]:
        sniffed = []

        def _on_req(req):
            if "token=" in req.url and ("vergabe24.de" in req.url or "tender24.de" in req.url):
                sniffed.append(req.url)

        page.on("request", _on_req)
        try:
            resp = await page.goto(target_url, wait_until="domcontentloaded", timeout=TIMEOUT_PAGE)
            await dismiss_cookies(page)

            # vergabe24/tender24 — wait for JS token redirect
            if "vergabe24.de" in target_url or "tender24.de" in target_url:
                for _ in range(12):
                    if "token=" in page.url or sniffed:
                        break
                    await page.wait_for_timeout(1000)
                    await dismiss_cookies(page)
                if sniffed and "token=" not in page.url:
                    await page.goto(sniffed[0], wait_until="domcontentloaded", timeout=TIMEOUT_PAGE)
                    await dismiss_cookies(page)
                await page.wait_for_timeout(1500)
            else:
                await page.wait_for_timeout(800)

            final_url = page.url
            if resp and resp.status >= 400:
                return None

            text = await get_page_text(page)
            if not text or len(text) < 50:
                return None
            if _is_login_wall(text) or _is_gone(text):
                return None

            return text, final_url
        except Exception as e:
            log.debug(f"    [{label}] failed: {str(e)[:60]}")
            return None
        finally:
            page.remove_listener("request", _on_req)

    # vergabe24 HTTP-level recovery first
    netloc = urlparse(url).netloc.lower()
    if "vergabe24" in netloc or "tender24" in netloc:
        rec = recover_vergabe24_url(url)
        if rec["found_url"]:
            res = await _try(rec["found_url"], "vergabe24-recovery")
            if res:
                return res[0], res[1], f"vergabe24_{rec['strategy']}"

    # Attempt 1: normalised URL
    res = await _try(url, "original")
    if res:
        return res[0], res[1], None

    # Attempt 2: strip /documents suffix
    stripped = strip_documents_suffix(url)
    if stripped:
        res = await _try(stripped, "strip-docs")
        if res:
            return res[0], res[1], "strip_documents"

    return "", url, None


# ═══════════════════════════════════════════════════════════════════════════
#  LAYER 1 — FAST SCRAPER (known selectors for German portals)
# ═══════════════════════════════════════════════════════════════════════════

_FAST_SELECTORS = [
    # text-content buttons / tabs
    "xpath=//button[contains(text(),'Vergabeunterlagen')]",
    "xpath=//button[contains(text(),'Dokumente')]",
    "xpath=//a[contains(text(),'Vergabeunterlagen')]",
    "xpath=//a[contains(text(),'Dokumente')]",
    # tab patterns
    "xpath=//a[@id='documents-tab']",
    "xpath=//a[@href='#documents']",
    "xpath=//a[@href='#unterlagen']",
    # DevExtreme tabs (used by many German portals)
    "xpath=//div[contains(@class,'dx-tab')]//span[contains(text(),'Dokumente')]",
    "xpath=//div[contains(@class,'dx-tab')]//span[contains(text(),'Unterlagen')]",
]


async def fast_scrape(page) -> bool:
    """
    Layer 1: click a known portal tab/button to reveal the documents section.
    Returns True if a click succeeded (page state changed).
    """
    for sel in _FAST_SELECTORS:
        try:
            el = page.locator(sel).first
            if await el.is_visible(timeout=500):
                await el.click()
                await page.wait_for_timeout(800)
                log.debug(f"    [L1] clicked: {sel}")
                return True
        except Exception:
            pass
    return False


# ═══════════════════════════════════════════════════════════════════════════
#  LAYER 2 — HEURISTIC SCRAPER (keyword-scored link scan)
# ═══════════════════════════════════════════════════════════════════════════

_DOC_EXTENSIONS = {
    ".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx",
    ".rar", ".7z", ".odt", ".ods", ".p7s",
    ".gaeb", ".x81", ".x83", ".d83", ".d84",
}

_DOC_TEXT_KW = [
    "unterlag", "leistungsverzeichnis", "vergabeunterlag", "angebotsunterlag",
    "teilnahmeunterlag", "gaeb", "formular", "bewerbungsbogen",
    "herunterladen", "download", "dokument", "alle dokumente", "bieterunterlagen",
]

_DOC_SKIP_TEXT = [
    "agb", "datenschutz", "impressum", "nutzungsbedingung", "hilfe",
    "registrierung", "anmelden", "login", "startseite", "cookie",
]

_DOC_URL_KW = [
    "unterlag", "leistung", "vergabe", "gaeb", "dokument",
    "formular", "download", "attachment", "file", "bieter",
]

_REVEAL_XPATHS = [
    "//button[contains(.,'Vergabeunterlagen')]",
    "//button[contains(.,'Unterlagen')]",
    "//button[contains(.,'Dokumente')]",
    "//button[contains(.,'Dokumente anzeigen')]",
    "//a[contains(@class,'tab') and contains(.,'Unterlagen')]",
    "//div[contains(@class,'accordion') and contains(.,'Unterlagen')]//button",
]


def _score_link(href: str, text: str, page_domain: str) -> int:
    """Score 0-3: how likely this link leads to a tender document."""
    lh = href.lower()
    lt = (text or "").lower()
    link_domain = urlparse(href).netloc.lower()

    # Cross-domain skip unless it's a known doc portal
    if link_domain and link_domain != page_domain:
        if not any(x in link_domain for x in ["evergabe", "vergabe", "subreport", "tender24"]):
            return 0

    if any(k in lh for k in ["/agb", "/datenschutz", "/impressum", ".css", ".js", ".png", ".jpg"]):
        return 0
    if any(k in lt for k in _DOC_SKIP_TEXT):
        return 0

    ext = Path(urlparse(href).path).suffix.lower()
    has_ext   = ext in _DOC_EXTENSIONS
    has_text  = any(k in lt for k in _DOC_TEXT_KW)
    has_url   = any(k in lh for k in _DOC_URL_KW)

    if not has_ext and not has_text and not has_url:
        return 0

    score = 0
    if has_ext:   score += 1
    if has_text:  score += 2
    elif has_url: score += 1
    return min(score, 3)


async def _collect_links(page, base_url: str) -> List[Tuple[str, str, int]]:
    """Collect and score all candidate document links on the page."""
    page_domain = urlparse(base_url).netloc.lower()
    candidates, seen = [], set()
    try:
        for link in await page.locator("xpath=//a[@href]").all():
            try:
                href = await link.get_attribute("href")
                if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                full = urljoin(base_url, href)
                if full in seen:
                    continue
                seen.add(full)
                text = (await link.inner_text()).strip()
                sc = _score_link(full, text, page_domain)
                if sc > 0:
                    candidates.append((full, text, sc))
            except Exception:
                pass
    except Exception:
        pass
    candidates.sort(key=lambda x: -x[2])
    return candidates


async def heuristic_scrape(page) -> bool:
    """
    Layer 2: click reveal buttons then scan for high-score document links.
    Returns True if at least one strong link (score ≥ 2) was found.
    """
    # Try reveal buttons
    for xp in _REVEAL_XPATHS:
        try:
            el = page.locator(f"xpath={xp}").first
            if await el.is_visible(timeout=400):
                await el.click()
                await page.wait_for_timeout(700)
        except Exception:
            pass

    # Also try JS-based tab expansion
    try:
        await page.evaluate("""
            document.querySelectorAll(
                '[data-tab="documents"],[data-tab="unterlagen"],'
                + '[href="#documents"],[href="#unterlagen"]'
            ).forEach(el => { try { el.click(); } catch(e) {} });
        """)
        await page.wait_for_timeout(400)
    except Exception:
        pass

    candidates = await _collect_links(page, page.url)
    strong = [c for c in candidates if c[2] >= 2]
    log.debug(f"    [L2] {len(candidates)} links, {len(strong)} strong")
    return len(strong) > 0


# ═══════════════════════════════════════════════════════════════════════════
#  LAYER 3 — CUA AGENT (OpenRouter + browser-use)
# ═══════════════════════════════════════════════════════════════════════════

async def run_agent(url: str) -> bool:
    """
    Layer 3: spin up a browser-use agent to handle difficult pages.
    Uses OPENROUTER_API_KEY from env. Returns True on success.

    NOTE: browser-use creates its own browser instance. This is intentional —
    the agent needs full control for vision-based interaction.
    """
    try:
        from browser_use.llm.openrouter.chat import ChatOpenRouter
        from browser_use import Agent, Browser
    except ImportError:
        log.warning("    [L3] browser-use / langchain-openai not installed — skipping agent")
        return False

    api_key = OPENROUTER_API_KEY
    if not api_key:
        log.warning("    [L3] OPENROUTER_API_KEY not set — skipping agent")
        return False

    llm = ChatOpenRouter(
        api_key=api_key,
        model=MODEL_CHAIN[0],
    )
    downloads_path = os.path.join(os.getcwd(), "downloads")
    os.makedirs(downloads_path, exist_ok=True)
    browser = Browser(headless=True, downloads_path=downloads_path)

    task = f"""
    Objective: Download all tender documents from {url}.
    
    1. Navigate to the page.
    2. Handle any cookie/consent banners immediately.
    3. Locate 'Vergabeunterlagen' or 'Downloads'.
    4. Click to download all available files (PDF/ZIP).
    5. VISUAL VERIFICATION: Before finishing, look at the screen and confirm that the download links actually changed state or initiated a download. Ensure you didn't miss any visible documents.
    6. Conclude only after verifying the downloads were successful.
    """

    agent = Agent(task=task, llm=llm, browser=browser)
    try:
        await agent.run()
        await browser.stop()
        log.info(f"    [L3] agent succeeded: {url[:70]}")
        return True
    except Exception as e:
        await browser.stop()
        log.error(f"    [L3] agent failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  DOCUMENT DOWNLOAD  (from v5, integrated with layer results)
# ═══════════════════════════════════════════════════════════════════════════

def _safe_filename(s: str, maxlen: int = 120) -> str:
    s = re.sub(r"[^\w.\-]", "_", unquote(str(s)))
    return re.sub(r"_+", "_", s).strip("_")[:maxlen]


def _tender_folder(download_dir: str, tender_id: str) -> str:
    safe_id = re.sub(r"[^\w\-]", "_", str(tender_id))[:60]
    return os.path.join(download_dir, safe_id)


async def _fetch_one(page, doc_url: str, base_url: str, folder: str,
                     idx: int, content_hashes: set) -> Optional[str]:
    """Fetch a single document URL and save it to disk. Returns filename or None."""
    try:
        resp = await page.context.request.get(
            doc_url,
            timeout=TIMEOUT_DOWNLOAD,
            headers={
                "Accept": "application/pdf,application/zip,application/octet-stream,*/*;q=0.8",
                "Referer": base_url,
                "Accept-Language": "de-DE,de;q=0.9",
            },
        )
        if resp.status >= 400:
            return None

        ct = resp.headers.get("content-type", "").lower()
        if "text/html" in ct:
            return None

        body = await resp.body()
        if len(body) < 300:
            return None

        # dedup by content hash
        chash = hashlib.md5(body[:4096]).hexdigest()
        if chash in content_hashes:
            return None
        content_hashes.add(chash)

        # derive filename
        cd = resp.headers.get("content-disposition", "")
        filename = ""
        m = re.search(r"filename\*=(?:UTF-8'')?([^\s;]+)", cd, re.IGNORECASE)
        if m:
            filename = unquote(m.group(1))
        if not filename:
            m = re.search(r'filename=["\']?([^"\';\r\n]+)', cd)
            if m:
                filename = m.group(1).strip("\"' ")
        if not filename:
            filename = unquote(urlparse(doc_url).path.split("/")[-1].split("?")[0])

        if not filename or filename.lower() in {"download", "document", "file", ""}:
            ext_map = {
                "pdf": "pdf", "zip": "zip", "msword": "doc",
                "vnd.openxmlformats": "docx", "vnd.ms-excel": "xls",
            }
            ext = next((v for k, v in ext_map.items() if k in ct), "bin")
            filename = f"doc_{idx + 1}_{chash[:6]}.{ext}"

        filename = _safe_filename(filename)
        dest = os.path.join(folder, filename)
        if os.path.exists(dest):
            return filename

        with open(dest, "wb") as fh:
            fh.write(body)
        log.info(f"    ↓ {filename}  ({len(body) // 1024}KB)")
        return filename

    except Exception as e:
        log.debug(f"    fetch failed {doc_url[:60]}: {str(e)[:60]}")
        return None


async def download_documents(page, tender_id: str, base_url: str,
                             download_dir: str) -> List[str]:
    """
    Download all scored document links from the current page state.
    Reuses the same page/context (no extra browser tabs).
    """
    folder = _tender_folder(download_dir, tender_id)
    os.makedirs(folder, exist_ok=True)

    candidates = await _collect_links(page, base_url)
    saved, attempted, content_hashes = [], set(), set()
    threshold = 2 if any(c[2] >= 2 for c in candidates) else 1

    for doc_url, _, score in candidates:
        if len(saved) >= MAX_DOCS_PER_URL:
            break
        if score < threshold or doc_url in attempted:
            continue
        attempted.add(doc_url)
        fn = await _fetch_one(page, doc_url, base_url, folder, len(saved), content_hashes)
        if fn:
            saved.append(fn)

    return saved


# ═══════════════════════════════════════════════════════════════════════════
#  XPATH DATA EXTRACTION  (Phase 1, from v5)
# ═══════════════════════════════════════════════════════════════════════════

_FIELD_XPATHS = {
    "title": [
        "//h1",
        "//*[contains(@class,'title') and (self::h1 or self::h2)]",
        "//title",
    ],
    "authority": [
        "//dt[contains(.,'Auftraggeber')]/following-sibling::dd[1]",
        "//th[contains(.,'Auftraggeber')]/following-sibling::td[1]",
        "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
        "//*[contains(text(),'Vergabestelle')]/following-sibling::*[1]",
    ],
    "description": [
        "//*[contains(text(),'Beschreibung')]/following-sibling::*[1]",
        "//*[contains(@class,'description')]",
    ],
    "deadline": [
        "//dt[contains(.,'Angebotsfrist') or contains(.,'Frist')]/following-sibling::dd[1]",
        "//*[contains(text(),'Angebotsfrist')]/following-sibling::*[1]",
        "//*[contains(text(),'Abgabetermin')]/following-sibling::*[1]",
    ],
    "pub_date": [
        "//dt[contains(.,'Veröffentlich')]/following-sibling::dd[1]",
        "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
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
        "//*[contains(text(),'Erfüllungsort')]/following-sibling::*[1]",
        "//dt[contains(.,'Ort')]/following-sibling::dd[1]",
    ],
    "ref_num": [
        "//dt[contains(.,'Vergabenummer') or contains(.,'Aktenzeichen')]/following-sibling::dd[1]",
        "//*[contains(text(),'Vergabenummer')]/following-sibling::*[1]",
    ],
    "contact": [
        "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
        "//*[contains(@class,'contact')]",
    ],
}


async def xpath_extract(page) -> dict:
    """Extract tender fields using XPath selectors. Falls back to dt/dd scan."""
    out = {}
    for field, xpaths in _FIELD_XPATHS.items():
        for xp in xpaths:
            try:
                els = await page.locator(f"xpath={xp}").all()
                if els:
                    txt = (await els[0].inner_text()).strip()
                    if txt and len(txt) < 2000:
                        out[field] = txt
                        break
            except Exception:
                pass

    # dt/dd fallback if nothing found
    if not out.get("title") and not out.get("authority"):
        try:
            for dt in await page.locator("xpath=//dt").all():
                label = (await dt.inner_text()).strip().lower()
                value = await dt.evaluate("el => el.nextElementSibling?.textContent?.trim()")
                if not label or not value or len(label) > 100:
                    continue
                if "auftraggeber" in label or "vergabestelle" in label:
                    out.setdefault("authority", value)
                elif "frist" in label:
                    out.setdefault("deadline", value)
                elif "veröffentlich" in label:
                    out.setdefault("pub_date", value)
                elif "verfahren" in label:
                    out.setdefault("proc_type", value)
        except Exception:
            pass

    return out


# ═══════════════════════════════════════════════════════════════════════════
#  LLM DATA EXTRACTION  (from v5)
# ═══════════════════════════════════════════════════════════════════════════

_LLM_PROMPT = """Extract procurement tender data from this German page text.
URL: {url}

PAGE TEXT:
{text}

Return ONLY valid JSON. No markdown, no backticks, no explanation. Use null for missing fields.

{{"title":"tender title","authority":"Auftraggeber/Vergabestelle","description":"what is being procured (2-3 sentences)","deadline":"Angebotsfrist date","pub_date":"Veröffentlichungsdatum","proc_type":"Verfahrensart","cpv":"CPV codes","location":"Erfüllungsort","ref_num":"Vergabenummer","contact":"contact info"}}"""


def extract_with_llm(client, text: str, url: str) -> Tuple[Optional[dict], Optional[str], int, float]:
    """Call LLM to extract structured tender data. Returns (data, model, tokens, cost)."""
    prompt = _LLM_PROMPT.format(url=url, text=text)
    STATS["llm_calls"] += 1

    for model in MODEL_CHAIN:
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
                tokens = getattr(resp.usage, "total_tokens", 0) or 0
                cost   = float(getattr(resp.usage, "cost", 0) or 0)
                STATS["llm_tokens"] += tokens
                STATS["llm_cost"]   += cost

                raw = (resp.choices[0].message.content or "").strip()
                raw = re.sub(r"^```[a-z]*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw).strip()
                if not raw:
                    continue
                return json.loads(raw), model, tokens, cost

            except json.JSONDecodeError:
                log.debug(f"    bad JSON from {model} attempt {attempt + 1}")
                time.sleep(0.3)
            except Exception as e:
                msg = str(e)
                log.debug(f"    {model} error: {msg[:80]}")
                if "rate" in msg.lower() or "429" in msg:
                    break
                time.sleep(0.5)

    return None, None, 0, 0.0


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN WORKER — scrape one URL
# ═══════════════════════════════════════════════════════════════════════════

async def scrape_one(page, row: dict, client=None, use_llm: bool = False,
                     download_docs: bool = False,
                     download_dir: str = DOWNLOAD_DIR) -> dict:
    """
    Full pipeline for one URL:
      load → layer 1 → layer 2 → (layer 3) → extract → (download)
    """
    url = row.get("url", "").strip()
    domain = urlparse(url).netloc.lower()
    result = empty_result(row, domain)
    t0 = time.time()

    try:
        # ── load page ──────────────────────────────────────────────────────
        page_text, used_url, recovery = await load_with_recovery(page, url)
        result["url_used"]    = used_url
        result["url_recovery"] = recovery
        if recovery:
            STATS["url_recoveries"][recovery] = STATS["url_recoveries"].get(recovery, 0) + 1
            log.info(f"    🔄 recovered via {recovery}: {used_url[:60]}")

        if not page_text or len(page_text) < 50:
            result["status"] = "error"
            result["err"]    = "empty page after all recovery attempts"
            return result

        # ── Layer 1: fast selector ─────────────────────────────────────────
        layer1_ok = await fast_scrape(page)

        # ── Layer 2: heuristic + reveal ────────────────────────────────────
        # (always runs — layer 1 may have revealed new content)
        layer2_ok = await heuristic_scrape(page)

        layer = None
        if layer1_ok:
            layer = "fast"
            STATS["fast_success"] += 1
        elif layer2_ok:
            layer = "heuristic"
            STATS["heuristic_success"] += 1

        result["layer"] = layer

        # ── Extraction ─────────────────────────────────────────────────────
        if use_llm and client:
            data, model, tok, cost = extract_with_llm(client, page_text, used_url)
            result["model_used"] = model
            result["llm_tokens"] = tok
            result["llm_cost"]   = cost
            if data:
                for f in ("title", "authority", "description", "deadline",
                          "pub_date", "proc_type", "cpv", "location", "ref_num", "contact"):
                    result[f] = data.get(f)
            # XPath fallback if LLM returned nothing
            if not result["title"] and not result["authority"]:
                xd = await xpath_extract(page)
                for k, v in xd.items():
                    if not result.get(k):
                        result[k] = v
                if result["title"] or result["authority"]:
                    result["model_used"] = "xpath_fallback"
        else:
            xd = await xpath_extract(page)
            for k, v in xd.items():
                result[k] = v

        # ── Status after extraction ────────────────────────────────────────
        if result["title"] or result["authority"]:
            result["status"] = "success"
        else:
            result["status"] = "error"
            result["err"]    = "nothing extracted"

        # ── Layer 3: agent fallback (only if both layers AND extraction failed) ──
        if result["status"] == "error" and not layer1_ok and not layer2_ok:
            log.info(f"    falling back to agent: {url[:60]}")
            agent_ok = await run_agent(url)
            if agent_ok:
                result["layer"]  = "agent"
                result["status"] = "success"
                STATS["agent_success"] += 1
            else:
                result["status"] = "failed"
                STATS["failed"] += 1

        # ── Document download ──────────────────────────────────────────────
        if download_docs and result["status"] == "success":
            try:
                tid = result["id"] or re.sub(r"[^\w]", "_", used_url[-40:])
                docs = await download_documents(page, tid, used_url, download_dir)
                result["downloaded_docs"] = docs
                if docs:
                    log.info(f"    saved {len(docs)} doc(s)")
            except Exception as e:
                log.debug(f"    download error: {e}")
                result["err"] = f"download: {str(e)[:100]}"

    except Exception as e:
        result["status"] = "error"
        result["err"]    = str(e)[:300]
        if "closed" not in str(e).lower():
            log.error(f"    !!! {url[:60]}: {e}")
        STATS["error"] += 1

    result["ms"] = int((time.time() - t0) * 1000)
    result["ts"] = datetime.now().isoformat()
    STATS["total"] += 1
    return result


# ═══════════════════════════════════════════════════════════════════════════
#  DOMAIN RUNNER — one tab per domain (reuse tab across URLs)
# ═══════════════════════════════════════════════════════════════════════════

async def run_domain(domain: str, rows: list, results: list,
                     sem: asyncio.Semaphore, ctx, prog: dict, total: int,
                     client, use_llm: bool, download_docs: bool,
                     download_dir: str):
    log.info(f"  {domain}  ({len(rows)} urls)")
    page = await ctx.new_page()

    for row in rows:
        async with sem:
            if page.is_closed():
                try:
                    page = await ctx.new_page()
                except Exception:
                    continue

            rec = await scrape_one(
                page, row,
                client=client, use_llm=use_llm,
                download_docs=download_docs, download_dir=download_dir,
            )
            results.append(rec)

            prog["n"] += 1
            n = prog["n"]
            icon = {"success": "✓", "failed": "✗", "error": "!"}.get(rec["status"], "?")
            rlabel = f" [{rec['url_recovery']}]" if rec.get("url_recovery") else ""
            llabel = f" [{rec['layer']}]" if rec.get("layer") else ""
            log.info(
                f"  {icon} [{n}/{total} {100*n/total:.0f}%] "
                f"{domain} {rec['status']} {rec['ms']}ms{llabel}{rlabel}"
            )

    try:
        if not page.is_closed():
            await page.close()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════
#  OUTPUT
# ═══════════════════════════════════════════════════════════════════════════

CSV_COLUMNS = [
    "id", "url", "url_used", "domain", "status", "layer",
    "title", "authority", "description", "deadline", "pub_date",
    "proc_type", "cpv", "location", "ref_num", "contact",
    "model_used", "llm_tokens", "llm_cost",
    "downloaded_docs", "url_recovery", "err", "ms", "ts",
]


def save_results(results: list, output_json: str) -> str:
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    csv_path = output_json.replace(".json", ".csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for rec in results:
            row = dict(rec)
            row["downloaded_docs"] = ";".join(rec.get("downloaded_docs") or [])
            writer.writerow(row)
    return csv_path


def print_summary(results: list, use_llm: bool, download_docs: bool):
    n = len(results) or 1
    ok  = sum(1 for r in results if r["status"] == "success")
    err = sum(1 for r in results if r["status"] in ("error", "failed"))
    rec = sum(1 for r in results if r.get("url_recovery"))
    avg = sum(r["ms"] for r in results) / n
    docs_saved = sum(len(r.get("downloaded_docs") or []) for r in results)
    sep = "=" * 60

    print(f"\n{sep}")
    print(f"  RESULTS  ({'LLM' if use_llm else 'XPath-only'})")
    print(sep)
    print(f"  total:          {n}")
    print(f"  success:        {ok}  ({100*ok/n:.1f}%)")
    print(f"    fast layer:   {STATS['fast_success']}")
    print(f"    heuristic:    {STATS['heuristic_success']}")
    print(f"    agent:        {STATS['agent_success']}")
    print(f"  errors/failed:  {err}  ({100*err/n:.1f}%)")
    print(f"  URL recovered:  {rec}  ({100*rec/n:.1f}%)")
    print(f"  avg time:       {avg:.0f}ms/url")
    if download_docs:
        print(f"  docs saved:     {docs_saved}")
    if STATS["url_recoveries"]:
        print(f"\n  URL recovery breakdown:")
        for strat, cnt in sorted(STATS["url_recoveries"].items(), key=lambda x: -x[1]):
            print(f"    {strat:30s}: {cnt}")
    if use_llm and STATS["llm_calls"]:
        print(f"\n  LLM:")
        print(f"    calls:   {STATS['llm_calls']}")
        print(f"    tokens:  {STATS['llm_tokens']:,}")
        print(f"    cost:    ${STATS['llm_cost']:.4f}")

    # per-domain table
    dom = {}
    for r in results:
        d = r["domain"]
        dom.setdefault(d, [0, 0])
        dom[d][1] += 1
        if r["status"] == "success":
            dom[d][0] += 1
    print(f"\n  domains:")
    for d, (s, t) in sorted(dom.items(), key=lambda x: -x[1][1]):
        print(f"    {d:50s} {s:>4}/{t:<4} ({100*s/t:.0f}%)")
    print(sep)


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════

async def main(args):
    use_llm = args.llm
    client  = None

    if use_llm:
        try:
            from openai import OpenAI
        except ImportError:
            print("pip install openai"); exit(1)

        api_key = args.api_key or OPENROUTER_API_KEY
        if not api_key:
            print("Set OPENROUTER_API_KEY or pass --api-key"); exit(1)

        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
        try:
            test = client.chat.completions.create(
                model=MODEL_CHAIN[0],
                messages=[{"role": "user", "content": "reply ok"}],
                max_tokens=5,
            )
            log.info(f"API ok: {test.choices[0].message.content or '(empty)'}")
        except Exception as e:
            print(f"API test failed: {e}"); exit(1)

    # Load CSV
    rows = []
    with open(args.input, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames and "url" in reader.fieldnames:
            rows = [r for r in reader if r.get("url", "").strip()]
        else:
            # plain URL list (no header)
            f.seek(0)
            for line in f:
                line = line.strip()
                if line:
                    rows.append({"url": line, "id": ""})

    log.info(f"{len(rows)} URLs loaded from {args.input}")

    if args.limit > 0:
        rows = rows[:args.limit]
        log.info(f"Limited to {args.limit}")

    if not rows:
        print("Nothing to scrape"); return

    if args.download_docs:
        os.makedirs(args.download_dir, exist_ok=True)
        log.info(f"Download dir: {args.download_dir}/")

    # Group by domain (tab reuse)
    groups: dict = {}
    for r in rows:
        d = urlparse(r["url"]).netloc.lower()
        groups.setdefault(d, []).append(r)
    for d, g in sorted(groups.items(), key=lambda x: -len(x[1])):
        log.info(f"    {d}: {len(g)} URLs")

    results: list = []
    sem   = asyncio.Semaphore(min(args.workers, 10))
    prog  = {"n": 0}
    total = len(rows)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                "--disable-extensions",
                "--blink-settings=imagesEnabled=false",
                "--disable-background-networking",
            ],
        )
        ctx = await browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            accept_downloads=True,
        )

        tasks = [
            run_domain(
                d, g, results, sem, ctx, prog, total,
                client, use_llm, args.download_docs, args.download_dir,
            )
            for d, g in groups.items()
        ]
        await asyncio.gather(*tasks)
        await browser.close()

    # Save
    csv_path = save_results(results, args.output)
    stats_path = args.output.replace(".json", "_stats.json")
    with open(stats_path, "w") as f:
        json.dump(STATS, f, indent=2)

    print_summary(results, use_llm, args.download_docs)
    log.info(f"Done → {args.output}  |  {csv_path}  |  {stats_path}")


# ═══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="German procurement tender scraper — 3-layer hybrid"
    )
    parser.add_argument("-i", "--input",        default="publications_b.csv")
    parser.add_argument("-o", "--output",       default="results.json")
    parser.add_argument("-w", "--workers",      type=int, default=MAX_CONCURRENT)
    parser.add_argument("-n", "--limit",        type=int, default=0, help="0 = all")
    parser.add_argument("--llm",               action="store_true")
    parser.add_argument("--api-key",           default=None)
    parser.add_argument("--download-docs",     action="store_true")
    parser.add_argument("--download-dir",      default=DOWNLOAD_DIR)
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"File not found: {args.input}"); exit(1)

    asyncio.run(main(args))