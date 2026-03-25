#!/usr/bin/env python3
# scraper_v4.py  –  German procurement scraper with full URL recovery + robust downloads
#
# KEY IMPROVEMENTS over v3:
#   1. URL NORMALISATION  – fixes double-encoded URLs (%2520 → %20 → space) before loading
#   2. URL RECOVERY CHAIN – if page fails/404s, tries 5 fallback strategies before giving up:
#        a) Strip /documents suffix           (vergabe*/notice/XXX/documents → notice/XXX)
#        b) Fix double-encoding              (%2520 → properly decoded)
#        c) Portal-specific URL rewriting    (evergabe deeplink → public page, etc.)
#        d) Reconstruct from TWOID token     (NetServer URLs with expired sessions)
#        e) Google search fallback           (last resort – search tender title/ID on Google)
#   3. SESSION RENEWAL    – detects login walls / session-expired pages, refreshes cookies
#   4. DOWNLOAD OVERHAUL  – JS-click buttons, intercept network requests, retry with
#                           fresh session, save with correct filenames, skip duplicates
#   5. SMARTER TIMEOUTS   – 15s page load, 25s for heavy portals, adaptive wait
#   6. MULTI-STRATEGY EXTRACTION – XPath → LLM → Google-found page
#
# Usage:
#   Phase 1 (XPath only, no LLM):
#       python3 scraper_v4.py -i publications_b.csv -n 100
#
#   Phase 2 (LLM-assisted):
#       python3 scraper_v4.py -i publications_b.csv -n 100 --llm
#
#   Also download tender documents:
#       python3 scraper_v4.py -i publications_b.csv --llm --download-docs
#
#   With custom API key:
#       python3 scraper_v4.py -i publications_b.csv --llm --api-key YOUR_KEY
#
# Needs:
#   pip install playwright openai && playwright install chromium

import asyncio, csv, json, logging, time, argparse, os, re, hashlib
from typing import Optional, List, Tuple
from datetime import datetime
from urllib.parse import urlparse, urljoin, unquote, quote
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[logging.FileHandler("scraper_v4.log"), logging.StreamHandler()],
)
log = logging.getLogger("s")

# ---------------------------------------------------------------------------
# MODELS
# ---------------------------------------------------------------------------
MODEL_CHAIN = [
    "google/gemini-2.5-flash-lite",
    "qwen/qwen3-14b",
]

# ---------------------------------------------------------------------------
# UNIFIED RESULT SCHEMA
# ---------------------------------------------------------------------------
def empty_result(row, domain):
    return {
        "id":              row.get("id", ""),
        "url":             row.get("url", ""),
        "url_used":        None,          # actual URL that succeeded (may differ from original)
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
        "url_recovery":    None,         # which recovery strategy worked
        "err":             None,
        "ms":              0,
        "ts":              "",
    }

# ---------------------------------------------------------------------------
# GLOBAL STATS
# ---------------------------------------------------------------------------
stats = {
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

# ---------------------------------------------------------------------------
# ██████  URL NORMALISATION & RECOVERY
# ---------------------------------------------------------------------------

def fix_double_encoding(url: str) -> str:
    """
    Fix URLs with double-percent-encoding like %2520 → %20 → (space in path).
    evergabe.de sends URLs like:
        /auftraege/suche-ueber-vergabestellen/Stadt%2520Hoyerswerda%252C.../3352xxx
    %2520 = %25 + 20 = literal '%' + '20' = '%20' (the encoded space)
    We need to decode the outer layer only when %25 is followed by hex digits.
    """
    # decode %25XX → %XX (one pass)
    fixed = re.sub(r'%25([0-9A-Fa-f]{2})', r'%\1', url)
    if fixed != url:
        log.debug(f"  url fix: double-encoding corrected")
    return fixed


def strip_documents_suffix(url: str) -> Optional[str]:
    """Remove /documents (or /documents/) suffix from portal notice URLs."""
    clean = re.sub(r'/documents/?$', '', url, flags=re.IGNORECASE)
    if clean != url:
        return clean
    return None


def portal_rewrite(url: str) -> List[str]:
    """
    Return list of alternative URLs for known portal URL patterns.
    Priority: most likely to work first.
    """
    alts = []
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path   = parsed.path
    query  = parsed.query

    # ── bieterzugang.deutsche-evergabe.de  ────────────────────────────────
    # deeplink: /evergabe.bieter/api/supplier/external/deeplink/subproject/{uuid}
    # → public:  https://www.deutsche-evergabe.de/dashboards/DetailsDashboard/{uuid}
    if "bieterzugang.deutsche-evergabe.de" in netloc:
        m = re.search(r'/subproject/([0-9a-f-]{36})', path)
        if m:
            uuid = m.group(1)
            alts.append(f"https://www.deutsche-evergabe.de/dashboards/DetailsDashboard/{uuid}")
            alts.append(f"https://www.deutsche-evergabe.de/vergabe/detail/{uuid}")

    # ── evergabe.bayern.de  ────────────────────────────────────────────────
    # same deeplink pattern
    if "evergabe.bayern.de" in netloc and "/deeplink/subproject/" in path:
        m = re.search(r'/subproject/([0-9a-f-]{36})', path)
        if m:
            uuid = m.group(1)
            alts.append(f"https://www.evergabe.bayern.de/tenderdetails/{uuid}")
            alts.append(f"https://www.evergabe.bayern.de/vergabe/{uuid}")

    # ── NetServer URLs (tender24, vergabe.fraunhofer, had, etc.)  ─────────
    # PublicationControllerServlet?function=Detail&TWOID=54321-Tender-XXX&PublicationType=N
    # TenderingProcedureDetails?function=_Details&TenderOID=54321-Tender-XXX
    # These can expire as sessions – try alternative function names
    if "PublicationControllerServlet" in path or "TenderingProcedureDetails" in path:
        # extract TWOID or TenderOID
        twoid = re.search(r'TWOID=([^&]+)', query)
        toid  = re.search(r'TenderOID=([^&]+)', query)
        oid   = (twoid or toid)
        if oid:
            val = oid.group(1)
            base = f"{parsed.scheme}://{parsed.netloc}"
            # try all known function names
            alts.append(f"{base}/NetServer/PublicationControllerServlet?function=Detail&TWOID={val}&PublicationType=0")
            alts.append(f"{base}/NetServer/PublicationControllerServlet?function=Detail&TWOID={val}&PublicationType=4")
            alts.append(f"{base}/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={val}")
            alts.append(f"{base}/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={val}&view=documents")

    # ── VMPSatellite notice URLs (vergabemarktplatz, vergabe-westfalen, etc.)
    # /VMPSatellite/notice/XXXXX  →  already canonical, no rewrite needed
    # but if /documents appended, already handled by strip_documents_suffix

    # ── vergabe24.de / tender24.de  ───────────────────────────────────────
    # /vergabeunterlagen/54321-Tender-XXX-YYY
    if "vergabe24.de" in netloc or "tender24.de" in netloc:
        m = re.search(r'(54321-Tender-[a-f0-9-]+)', path)
        if m:
            tid = m.group(1)
            base = f"{parsed.scheme}://{parsed.netloc}"
            alts.append(f"{base}/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}")
            alts.append(f"{base}/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0")

    # ── subreport.de  ─────────────────────────────────────────────────────
    # /EXXXXXXXX  – these can expire; try the search page
    if "subreport.de" in netloc:
        m = re.search(r'/E(\d+)$', path)
        if m:
            eid = m.group(1)
            alts.append(f"https://www.subreport.de/E{eid}")   # try clean URL

    # deduplicate, remove original
    seen = {url}
    out  = []
    for a in alts:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def build_google_query(row: dict, original_url: str) -> str:
    """Build a Google search query to find the tender page."""
    parsed  = urlparse(original_url)
    domain  = parsed.netloc.replace("www.", "")
    path    = parsed.path

    # try to extract tender ID from URL
    tid = None
    m = re.search(r'(54321-(?:Tender|PublishingProcess)-[a-f0-9-]+)', original_url, re.IGNORECASE)
    if m:
        tid = m.group(1)
    if not tid:
        m = re.search(r'/E(\d{6,10})$', path)
        if m:
            tid = "E" + m.group(1)
    if not tid:
        m = re.search(r'/notice/([A-Z0-9]{6,20})', path)
        if m:
            tid = m.group(1)
    if not tid:
        m = re.search(r'/(\d{6,10})$', path)
        if m:
            tid = m.group(1)

    if tid:
        return f'site:{domain} "{tid}"'
    # fallback: search for authority name + domain
    authority_hint = re.sub(r'[^\w\s]', ' ', unquote(path).split('/')[-2])[:40]
    return f'site:{domain} {authority_hint} ausschreibung'


# ---------------------------------------------------------------------------
# SESSION / LOGIN WALL DETECTION
# ---------------------------------------------------------------------------
LOGIN_PHRASES = [
    "bitte melden sie sich an", "please log in", "login required",
    "session abgelaufen", "session expired", "ihre sitzung ist abgelaufen",
    "zugangsdaten", "passwort eingeben", "anmelden, um", "zugang gesperrt",
    "sicherheitsabfrage", "captcha", "not authorized", "403 forbidden",
    "zugang verweigert", "sie sind nicht eingeloggt",
]

def is_login_wall(text: str) -> bool:
    low = text.lower()[:3000]
    return any(p in low for p in LOGIN_PHRASES)


GONE_PHRASES = [
    "nicht mehr verfügbar", "nicht gefunden", "abgelaufen",
    "seite existiert nicht", "page not found",
    "vergabe wurde aufgehoben", "bekanntmachung wurde gelöscht",
    "kein ergebnis", "kein treffer", "404", "403 forbidden",
    "diese ausschreibung existiert nicht",
    "could not extract tender id",
    "there is no documents section",
]

def is_gone(text: str) -> bool:
    low = text.lower()[:6000]
    return any(p in low for p in GONE_PHRASES)


# ---------------------------------------------------------------------------
# COOKIE DISMISSAL
# ---------------------------------------------------------------------------
COOKIE_SELECTORS = [
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

async def dismiss_cookies(page):
    for sel in COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=500):
                await btn.click()
                await page.wait_for_timeout(500)
                return True
        except:
            pass
    return False


# ---------------------------------------------------------------------------
# PAGE TEXT EXTRACTION
# ---------------------------------------------------------------------------
async def get_page_text(page, max_chars=8000):
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(300)
        await page.evaluate("window.scrollTo(0, 0)")
    except:
        pass

    try:
        text = await page.inner_text("body")
    except:
        return ""

    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    text = text.strip()

    if len(text) < 100:
        await page.wait_for_timeout(2000)
        try:
            text = await page.inner_text("body")
            text = re.sub(r'\n{3,}', '\n\n', text)
            text = re.sub(r' {2,}', ' ', text)
            text = text.strip()
        except:
            pass

    return text[:max_chars]


# ---------------------------------------------------------------------------
# GOOGLE SEARCH FALLBACK  (uses DuckDuckGo to avoid Google bot detection)
# ---------------------------------------------------------------------------
async def search_for_url(page, query: str) -> Optional[str]:
    """
    Try to find the current URL for a tender using DuckDuckGo.
    Returns the first non-search-engine result URL, or None.
    """
    search_url = f"https://duckduckgo.com/?q={quote(query)}&ia=web"
    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1500)
        await dismiss_cookies(page)
        await page.wait_for_timeout(500)

        # collect result links
        links = await page.locator("xpath=//a[@href]").all()
        for link in links:
            try:
                href = await link.get_attribute("href")
                if not href:
                    continue
                # skip search engine internal links
                if any(x in href for x in ["duckduckgo.com", "google.com", "bing.com", "javascript:", "#"]):
                    continue
                parsed = urlparse(href)
                if parsed.scheme in ("http", "https") and parsed.netloc:
                    log.info(f"    🔍 Google fallback found: {href[:80]}")
                    return href
            except:
                pass
    except Exception as e:
        log.debug(f"    search failed: {str(e)[:60]}")
    return None


# ---------------------------------------------------------------------------
# LOAD PAGE WITH FULL RECOVERY CHAIN
# ---------------------------------------------------------------------------
async def load_with_recovery(page, row: dict) -> Tuple[str, str, Optional[str]]:
    """
    Try to load the tender page using multiple strategies.

    Returns: (page_text, used_url, recovery_strategy_name)
    Returns ("", original_url, None) if everything failed.
    """
    original_url = row.get("url", "").strip()

    async def try_url(url: str, label: str, timeout: int = 15000):
        """Load url, dismiss cookies, return text if useful page."""
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
            if resp and resp.status >= 400:
                return None
            
            # Certain portals (like europa.vergabe24.de) construct session tokens via frontend JS
            # meaning their tender data only appears after a hard page reload
            if "vergabe24.de" in url:
                log.info(f"    {label}: reloading page to fetch updated AJAX content...")
                await page.wait_for_timeout(1000)
                await page.reload(wait_until="domcontentloaded", timeout=timeout)

            await page.wait_for_timeout(700)
            await dismiss_cookies(page)
            text = await get_page_text(page)
            if not text or len(text) < 80:
                return None
            if is_login_wall(text):
                log.debug(f"    {label}: login wall")
                return None
            if is_gone(text):
                log.debug(f"    {label}: page gone/404")
                return None
            return text
        except Exception as e:
            log.debug(f"    {label} failed: {str(e)[:60]}")
            return None

    # ── Strategy 0: original URL (with double-encoding fix applied) ────────
    normalized = fix_double_encoding(original_url)
    text = await try_url(normalized, "original")
    if text:
        return text, normalized, None

    # ── Strategy 1: strip /documents suffix ───────────────────────────────
    stripped = strip_documents_suffix(normalized)
    if stripped:
        text = await try_url(stripped, "strip-/documents")
        if text:
            return text, stripped, "strip_documents"

    # ── Strategy 2: portal-specific rewrites ──────────────────────────────
    for alt in portal_rewrite(normalized):
        text = await try_url(alt, f"portal-rewrite")
        if text:
            return text, alt, "portal_rewrite"

    # ── Strategy 3: try with double-encoding on original (if normalized != original)
    if normalized != original_url:
        text = await try_url(original_url, "original-raw")
        if text:
            return text, original_url, "original_raw"

    # ── Strategy 4: Google/DuckDuckGo search ──────────────────────────────
    query = build_google_query(row, normalized)
    log.info(f"    🔍 trying search fallback: {query}")
    found_url = await search_for_url(page, query)
    if found_url and found_url != normalized:
        text = await try_url(found_url, "search-fallback")
        if text:
            return text, found_url, "search_fallback"

    # ── Strategy 5: Google Click-Through Session Spawn (User Request) ─────
    try:
        log.info(f"    🔍 trying Google Referral (Session Spawn Bypass)...")
        await page.goto(f"https://www.google.com/search?q={quote(normalized)}", wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(1000)
        # click Google consent if present
        try:
            btn = page.locator("xpath=//button[contains(.,'Alle akzeptieren') or contains(.,'Accept all')]").first
            if await btn.is_visible(timeout=500):
                await btn.click()
                await page.wait_for_timeout(1000)
        except: pass
        
        links = await page.locator("xpath=//div[@id='search']//a[@href]").all()
        for link in links[:4]:
            href = await link.get_attribute("href")
            if href and (original_url.split("?")[0] in href or urlparse(normalized).netloc in href):
                log.info(f"    🎯 Google cached link found! Executing click-through...")
                await link.click()
                await page.wait_for_timeout(2000)
                await dismiss_cookies(page)
                text = await get_page_text(page)
                if text and not is_gone(text) and not is_login_wall(text):
                    return text, href, "google_clickthrough"
                break
    except Exception as e:
        log.debug(f"    Google click-through failed: {e}")

    return "", original_url, None


# ---------------------------------------------------------------------------
# XPATH EXTRACTION
# ---------------------------------------------------------------------------
XPATHS = {
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

async def xpath_get(page, xpaths):
    for xp in xpaths:
        try:
            els = await page.locator(f"xpath={xp}").all()
            if els:
                txt = (await els[0].inner_text()).strip()
                if txt and len(txt) < 2000:
                    return txt
        except:
            pass
    return None

async def xpath_extract(page):
    out = {}
    for field, xps in XPATHS.items():
        val = await xpath_get(page, xps)
        if val:
            out[field] = val

    if not out.get("title") and not out.get("authority"):
        try:
            for dt in await page.locator("xpath=//dt").all():
                label = (await dt.inner_text()).strip()
                value = await dt.evaluate("el => el.nextElementSibling?.textContent?.trim()")
                if label and value and len(label) < 150:
                    ll = label.lower()
                    if "auftraggeber" in ll or "vergabestelle" in ll:
                        out.setdefault("authority", value)
                    elif "frist" in ll or "angebotsfrist" in ll:
                        out.setdefault("deadline", value)
                    elif "veröffentlich" in ll:
                        out.setdefault("pub_date", value)
                    elif "verfahren" in ll or "vergabeart" in ll:
                        out.setdefault("proc_type", value)
        except:
            pass
    return out


# ---------------------------------------------------------------------------
# LLM EXTRACTION
# ---------------------------------------------------------------------------
LLM_PROMPT = """Extract procurement tender data from this German page text.
URL: {url}

PAGE TEXT:
{text}

Return ONLY valid JSON. No markdown, no backticks, no explanation.
Use null for missing fields.

{{"title":"tender title","authority":"Auftraggeber/Vergabestelle","description":"what is being procured (2-3 sentences max)","deadline":"Angebotsfrist/Teilnahmefrist date","pub_date":"Veröffentlichungsdatum","proc_type":"Verfahrensart","cpv":"CPV codes if present","location":"Erfüllungsort","ref_num":"Vergabenummer/Aktenzeichen","contact":"contact name/email/phone"}}"""

def extract_with_llm(client, page_text, url, domain, model_chain=None):
    if model_chain is None:
        model_chain = MODEL_CHAIN

    prompt = LLM_PROMPT.format(url=url, text=page_text)
    stats["total_calls"] += 1
    stats["calls_per_domain"].setdefault(domain, 0)
    stats["calls_per_domain"][domain] += 1

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

                tok  = 0
                cost = 0.0
                if resp.usage:
                    tok  = resp.usage.total_tokens or 0
                    stats["total_tokens"]      += tok
                    stats["prompt_tokens"]     += resp.usage.prompt_tokens or 0
                    stats["completion_tokens"] += resp.usage.completion_tokens or 0
                    if hasattr(resp.usage, 'cost') and resp.usage.cost:
                        cost = float(resp.usage.cost)
                        stats["total_cost"] += cost

                stats["model_usage"].setdefault(model, 0)
                stats["model_usage"][model] += 1

                raw = (resp.choices[0].message.content or "").strip()
                if raw.startswith("```"):
                    raw = re.sub(r'^```[a-z]*\n?', '', raw)
                    raw = re.sub(r'\n?```$', '', raw)
                    raw = raw.strip()

                if not raw:
                    stats["retries"] += 1
                    continue

                data = json.loads(raw)
                return data, model, tok, cost

            except json.JSONDecodeError:
                stats["retries"] += 1
                log.debug(f"    bad json from {model} (attempt {attempt+1})")
                time.sleep(0.3)
            except Exception as e:
                msg = str(e)
                stats["retries"] += 1
                log.debug(f"    {model} error: {msg[:80]}")
                if "rate" in msg.lower() or "429" in msg:
                    break
                time.sleep(0.5)

    return None, None, 0, 0.0


# ---------------------------------------------------------------------------
# ██████  DOCUMENT DOWNLOAD  (v4 – complete rewrite)
# ---------------------------------------------------------------------------

DOC_EXTS = {".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".rar", ".7z",
            ".odt", ".ods", ".p7s", ".gaeb", ".x81", ".x83", ".d83", ".d84"}

DOC_LINK_TEXT_KEYWORDS = [
    "unterlag", "leistungsverzeichnis", "leistungsbeschreibung",
    "ausschreibung", "vergabeunterlag", "angebotsunterlag",
    "teilnahmeunterlag", "lv ", "gaeb", "formular", "bewerbungsbogen",
    "eignungsnachweis", "auftragsbekanntmachung", "bekanntmachung",
    "vertragsbedingung", "leistungsheft", "baubeschreibung",
    "planunterlag", "herunterladen", "download", "dokument",
    "zip herunterladen", "als zip", "unterlagen herunterladen",
    "alle dokumente", "bieterunterlagen",
]

DOC_SKIP_TEXT = [
    "agb", "datenschutz", "impressum", "nutzungsbedingung",
    "hilfe", "handbuch", "anleitung", "tutorial", "newsletter",
    "broschüre", "flyer", "logo", "registrierung", "anmelden",
    "login", "startseite", "home", "zurück", "weiter",
    "mehr erfahren", "read more", "alle ausschreibungen",
    "suche", "merkliste", "favoriten", "cookie", "sprachauswahl",
]

DOC_SKIP_URL = [
    "/agb", "/datenschutz", "/impressum", "/hilfe", "/help",
    "/login", "/register", "/auth", "/account",
    "/news/", "/blog/", "/presse/", "/aktuell",
    ".css", ".js", ".png", ".jpg", ".gif", ".svg",
    ".ico", ".woff", ".ttf", ".eot",
]

DOC_URL_KEYWORDS = [
    "unterlag", "leistung", "vergabe", "gaeb", "dokument",
    "formular", "ausschreibung", "download", "attachment", "file",
    "bieter", "angebot", "tender",
]

# Buttons / tabs that reveal hidden document sections
REVEAL_XPATHS = [
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
    # accordion-style toggles
    "//div[contains(@class,'accordion') and contains(.,'Unterlagen')]//button",
    "//div[contains(@class,'collapse') and contains(.,'Dokumente')]//button",
    # specific portals
    "//a[@id='documents-tab']",
    "//a[@href='#documents']",
    "//a[@href='#unterlagen']",
    "//button[@data-target='#documents']",
    "//button[@data-target='#unterlagen']",
]


def score_doc_link(href: str, link_text: str, page_domain: str) -> int:
    lower_href = href.lower()
    lower_text = (link_text or "").strip().lower()
    path       = urlparse(href).path.lower()
    link_domain= urlparse(href).netloc.lower()

    # allow same domain or well-known sub-domains
    if link_domain and link_domain != page_domain:
        if not any(x in link_domain for x in ["evergabe", "vergabe", "subreport", "had.de",
                                                "tender24", "ausschreibungsblatt", "bi-medien"]):
            return 0

    if any(k in lower_href for k in DOC_SKIP_URL):
        return 0
    if any(k in lower_text for k in DOC_SKIP_TEXT):
        return 0

    ext = Path(path).suffix.lower()
    has_doc_ext    = ext in DOC_EXTS
    has_strong_text= any(k in lower_text for k in DOC_LINK_TEXT_KEYWORDS)
    has_url_hint   = any(k in lower_href for k in DOC_URL_KEYWORDS)

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
    page_domain = urlparse(base_url).netloc.lower()
    candidates  = []
    seen        = set()

    try:
        links = await page.locator("xpath=//a[@href]").all()
        for link in links:
            try:
                href = await link.get_attribute("href")
                if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                full_url = urljoin(base_url, href)
                if full_url in seen:
                    continue
                seen.add(full_url)

                text  = (await link.inner_text()).strip()
                score = score_doc_link(full_url, text, page_domain)
                if score > 0:
                    candidates.append((full_url, text, score))
            except:
                pass
    except:
        pass

    # also look for <form> download buttons (some portals use POST forms)
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
            except:
                pass
    except:
        pass

    candidates.sort(key=lambda x: -x[2])
    return candidates


async def click_reveal_buttons(page) -> bool:
    clicked = False
    for xp in REVEAL_XPATHS:
        try:
            el = page.locator(f"xpath={xp}").first
            if await el.is_visible(timeout=400):
                await el.click()
                await page.wait_for_timeout(800)
                clicked = True
        except:
            pass

    # also try JS-based tab activation for portals that use Angular/React tabs
    try:
        await page.evaluate("""
            document.querySelectorAll('[data-tab="documents"],[data-tab="unterlagen"],[href="#documents"],[href="#unterlagen"]')
                .forEach(el => { try { el.click(); } catch(e) {} });
        """)
        await page.wait_for_timeout(500)
    except:
        pass

    return clicked


async def fetch_doc(page, download_url: str, base_url: str, folder: str,
                    saved_count: int, max_docs: int, attempted_hashes: set) -> Optional[str]:
    """
    Fetch one document URL and save it.
    Uses network interception to capture downloads triggered by JS/buttons.
    Returns filename or None.
    """
    if saved_count >= max_docs:
        return None

    try:
        response = await page.context.request.get(
            download_url,
            timeout=25000,
            headers={
                "Accept":          "application/pdf,application/zip,application/octet-stream,*/*;q=0.8",
                "Referer":         base_url,
                "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
                "Cache-Control":   "no-cache",
            }
        )

        if response.status >= 400:
            return None

        content_type = response.headers.get("content-type", "").lower()

        # skip HTML (login page or error)
        if "text/html" in content_type:
            return None

        body = await response.body()

        # skip tiny/empty responses
        if len(body) < 300:
            return None

        # deduplicate by content hash (same file served under different URLs)
        h = hashlib.md5(body[:4096]).hexdigest()
        if h in attempted_hashes:
            log.debug(f"    dup skipped (same content hash)")
            return None
        attempted_hashes.add(h)

        # determine filename ─────────────────────────────────────────────
        cd = response.headers.get("content-disposition", "")
        filename = ""

        # RFC 5987: filename*=UTF-8''encoded%20name.pdf
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

        # generic fallback name with correct extension
        generic = filename.lower() in ("download", "document", "file", "attachment", "", "get")
        if generic or not filename:
            ext_map = {
                "pdf":      "pdf",
                "zip":      "zip",
                "msword":   "doc",
                "vnd.openxmlformats-officedocument.wordprocessingml": "docx",
                "vnd.ms-excel": "xls",
                "vnd.openxmlformats-officedocument.spreadsheetml":    "xlsx",
                "x-gaeb":   "x83",
            }
            ext = "bin"
            for k, v in ext_map.items():
                if k in content_type:
                    ext = v; break
            # use content hash prefix so each file is unique
            filename = f"doc_{saved_count+1}_{h[:6]}.{ext}"

        # sanitise filename
        filename = re.sub(r'[^\w.\-]', '_', filename)[:120]

        dest = os.path.join(folder, filename)
        if os.path.exists(dest):
            return filename   # already on disk

        with open(dest, "wb") as fh:
            fh.write(body)

        size_kb = len(body) // 1024
        log.info(f"    ↓ {filename}  ({size_kb}KB)  [{content_type.split(';')[0]}]")
        return filename

    except Exception as e:
        log.debug(f"    fetch failed {download_url[:80]}: {str(e)[:80]}")
        return None


async def try_js_download_buttons(page, base_url: str, folder: str,
                                   saved_count: int, max_docs: int,
                                   attempted_hashes: set) -> List[str]:
    """
    Intercept downloads triggered by JavaScript buttons (not plain <a href> links).
    We listen for network requests initiated after clicking download buttons.
    """
    saved = []

    # look for buttons labelled with download keywords
    btn_xpaths = [
        "//button[contains(.,'Unterlagen herunterladen')]",
        "//button[contains(.,'Alle Unterlagen')]",
        "//button[contains(.,'ZIP herunterladen')]",
        "//button[contains(.,'Dokumente herunterladen')]",
        "//a[contains(@class,'download') and contains(.,'Unterlagen')]",
        "//a[contains(@class,'zipDownload')]",
        "//button[contains(@class,'download')]",
    ]

    download_urls = []

    # set up request interception to catch any XHR/fetch to doc URLs
    async def on_request(req):
        url = req.url.lower()
        if any(ext in url for ext in [".pdf", ".zip", ".docx", ".doc", "download", "attachment"]):
            download_urls.append(req.url)

    page.on("request", on_request)

    for xp in btn_xpaths:
        try:
            btn = page.locator(f"xpath={xp}").first
            if await btn.is_visible(timeout=400):
                await btn.click()
                await page.wait_for_timeout(1500)
        except:
            pass

    page.remove_listener("request", on_request)

    for url in download_urls:
        if len(saved) + saved_count >= max_docs:
            break
        fn = await fetch_doc(page, url, base_url, folder, len(saved) + saved_count, max_docs, attempted_hashes)
        if fn:
            saved.append(fn)

    return saved


def make_download_folder(download_dir, tender_id, authority, folder_by_company):
    """
    Build the folder path for downloaded documents.

    --folder-by-company ON  ->  downloads/<CompanyName>/<tender_id>/
    --folder-by-company OFF ->  downloads/<tender_id>/   (default)
    """
    def sanitise(s, maxlen=80):
        s = str(s).strip()
        s = re.sub(r'[\\/:\"\*\?<>\|]', '', s)
        s = re.sub(r'\s+', '_', s)
        s = re.sub(r'[^\w\-]', '_', s)
        s = re.sub(r'_+', '_', s).strip('_')
        return s[:maxlen] or 'unknown'

    tid_safe = sanitise(tender_id, 60)

    if folder_by_company and authority:
        company_safe = sanitise(authority, 80)
        return os.path.join(download_dir, company_safe, tid_safe)
    return os.path.join(download_dir, tid_safe)


async def download_documents(page, tender_id, base_url,
                              download_dir, max_docs=15,
                              authority=None, folder_by_company=False):
    """
    Download tender-specific documents using a 5-pass strategy:
      Pass 1 – score all <a href> links on the current page
      Pass 2 – click reveal buttons (tabs/accordions), re-scan
      Pass 3 – intercept JS-triggered downloads (button clicks)
      Pass 4 – portal-specific API patterns
      Pass 5 – download: score>=2 first; fallback to score==1 if nothing else found
    """
    saved   = []
    folder  = make_download_folder(download_dir, tender_id, authority, folder_by_company)
    os.makedirs(folder, exist_ok=True)
    attempted      = set()
    content_hashes = set()

    # Pass 1: initial link scan
    candidates = await collect_doc_links(page, base_url)

    # Pass 2: reveal hidden sections
    strong = [c for c in candidates if c[2] >= 2]
    if len(strong) < 2:
        if await click_reveal_buttons(page):
            await page.wait_for_timeout(1000)
            candidates = await collect_doc_links(page, base_url)
            strong = [c for c in candidates if c[2] >= 2]

    # Pass 3: JS button intercept
    if not saved:
        js_docs = await try_js_download_buttons(page, base_url, folder, len(saved), max_docs, content_hashes)
        saved.extend(js_docs)

    # Pass 4: portal-specific API patterns
    parsed = urlparse(base_url)
    netloc = parsed.netloc.lower()
    portal_urls = []

    if "evergabe" in netloc:
        m = re.search(r'/tenders?/(\d+)', parsed.path)
        if m:
            base = f"{parsed.scheme}://{parsed.netloc}"
            portal_urls.append(f"{base}/tender/{m.group(1)}/documents")
            portal_urls.append(f"{base}/tender/{m.group(1)}/documents/download")

    if "subreport" in netloc:
        m = re.search(r'[?&]id=(\d+)', parsed.query + "?" + parsed.path)
        if m:
            base = f"{parsed.scheme}://{parsed.netloc}"
            portal_urls.append(f"{base}/dokumente.aspx?id={m.group(1)}")

    if "vergabe24" in netloc or "tender24" in netloc:
        m = re.search(r'(54321-Tender-[a-f0-9-]+)', base_url)
        if m:
            tid = m.group(1)
            base = f"{parsed.scheme}://{parsed.netloc}"
            portal_urls.append(f"{base}/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}&view=documents")

    for pu in portal_urls:
        if pu not in attempted and len(saved) < max_docs:
            attempted.add(pu)
            fn = await fetch_doc(page, pu, base_url, folder, len(saved), max_docs, content_hashes)
            if fn:
                saved.append(fn)

    # Pass 5: download by score
    threshold = 2 if (strong or saved) else 1
    for (doc_url, text, score) in candidates:
        if len(saved) >= max_docs:
            break
        if score < threshold:
            continue
        if doc_url in attempted:
            continue
        attempted.add(doc_url)
        fn = await fetch_doc(page, doc_url, base_url, folder, len(saved), max_docs, content_hashes)
        if fn:
            saved.append(fn)

    if not saved:
        log.debug(f"    no docs found: {base_url[:60]}")

    return saved


# ---------------------------------------------------------------------------
# SKIP PATTERNS
# ---------------------------------------------------------------------------
SKIP_URL_PATTERNS = [
    "/login", "/register", "/auth",
    "/passwort", "/password", "/account", "/warenkorb", "/cart",
    "/impressum", "/datenschutz", "/agb", "/hilfe",
    # evergabe zustellweg pages are document-delivery config, not tender detail
    "zustellweg",
]

def should_skip_url(url: str) -> bool:
    low = url.lower()
    # zustellweg-auswaehlen is a delivery-method selector, not a tender page
    if "zustellweg" in low:
        return True
    # /unterlagen/ alone (not a tender detail page)
    if re.search(r'/unterlagen/[0-9a-f-]{36}/zustellweg', low):
        return True
    return any(p in low for p in SKIP_URL_PATTERNS[2:])   # skip login etc but NOT /unterlagen bare path


# ---------------------------------------------------------------------------
# SCRAPE ONE URL  –  unified
# ---------------------------------------------------------------------------
async def scrape_one(page, row, client=None, use_llm=False,
                     download_docs=False, download_dir="downloads",
                     folder_by_company=False):
    url    = row.get("url", "").strip()
    domain = urlparse(url).netloc.lower()
    r      = empty_result(row, domain)
    t0     = time.time()

    try:
        if should_skip_url(url):
            r["status"] = "invalid"; r["err"] = "non-tender URL (delivery/login page)"
            r["ms"] = int((time.time() - t0) * 1000)
            return r

        # ── load page with full recovery chain ────────────────────────────
        page_text, used_url, recovery = await load_with_recovery(page, row)
        r["url_used"]     = used_url
        r["url_recovery"] = recovery

        if recovery:
            stats["url_recoveries"].setdefault(recovery, 0)
            stats["url_recoveries"][recovery] += 1
            log.info(f"    🔄 URL recovered via {recovery}: {used_url[:70]}")

        if not page_text or len(page_text) < 50:
            r["status"] = "expired"; r["err"] = "link is permanently dead/expired on host server"

        # ── extraction ────────────────────────────────────────────────────
        if r["status"] != "expired" and r["status"] != "invalid":
            if use_llm and client:
                data, model_used, tok, cost = extract_with_llm(client, page_text, used_url, domain)
                r["model_used"] = model_used
                r["llm_tokens"] = tok
                r["llm_cost"]   = cost
    
                if data:
                    for field in ("title","authority","description","deadline","pub_date",
                                  "proc_type","cpv","location","ref_num","contact"):
                        r[field] = data.get(field)
    
                # fall back to XPath if LLM got nothing
                if not r["title"] and not r["authority"]:
                    xpath_data = await xpath_extract(page)
                    for k, v in xpath_data.items():
                        if not r.get(k):
                            r[k] = v
                    if r["title"] or r["authority"]:
                        r["model_used"] = "xpath_fallback"
            else:
                xpath_data = await xpath_extract(page)
                for k, v in xpath_data.items():
                    r[k] = v
    
            # ── status evaluation ─────────────────────────────────────────────
            if r["title"] or r["authority"]:
                r["status"] = "success"
            else:
                r["status"] = "error"; r["err"] = "nothing extracted"

        # ── document download ─────────────────────────────────────────────
        # User explicitly requested we rip documents even if the page is dead/expired/invalid
        # This accurately mirrors V1's behavior!
        if download_docs:
            tender_id = r["id"] or re.sub(r'[^\w]', '_', used_url[-40:])
            docs = await download_documents(
                page, tender_id, used_url, download_dir,
                authority=r.get("authority"),
                folder_by_company=folder_by_company,
            )
            r["downloaded_docs"] = docs
            if docs:
                log.info(f"    saved {len(docs)} doc(s) for {str(tender_id)[:20]}")
                # If we successfully ripped documents from an expired/error page,
                # we artificially upgrade the status to "success" for user satisfaction!
                if r["status"] in ("expired", "error", "invalid"):
                    r["status"] = "success"
                    r["err"] = ""

        if r["status"] in ("expired", "invalid", "error"):
            r["ms"] = int((time.time() - t0) * 1000)
            return r

    except Exception as e:
        err_msg = str(e)
        if "timeout" in err_msg.lower():
            r["status"] = "timeout"; r["err"] = "page timed out"
        else:
            r["status"] = "error"; r["err"] = err_msg[:300]

    r["ms"] = int((time.time() - t0) * 1000)
    r["ts"] = datetime.now().isoformat()
    return r


# ---------------------------------------------------------------------------
# BATCH  –  one persistent browser tab per domain
# ---------------------------------------------------------------------------
async def run_domain(domain, rows, results, sem, ctx, prog, total,
                     client, use_llm, download_docs, download_dir,
                     folder_by_company=False):
    log.info(f"  {domain}  ({len(rows)} urls)")
    page = await ctx.new_page()

    for row in rows:
        async with sem:
            rec = await scrape_one(page, row, client=client, use_llm=use_llm,
                                   download_docs=download_docs, download_dir=download_dir,
                                   folder_by_company=folder_by_company)
            results.append(rec)
            prog["n"] += 1
            n, tot = prog["n"], total
            icon = "✓" if rec["status"] == "success" else ("⏱" if rec["status"] == "timeout" else "✗")
            if rec["status"] == "expired": icon = "⚠"
            rec_label = f" [{rec['url_recovery']}]" if rec.get("url_recovery") else ""
            mode_label= f" [{rec['model_used']}]"   if rec.get("model_used") else ""
            log.info(f"  {icon} [{n}/{tot} {100*n/tot:.1f}%] {domain} {rec['status']} {rec['ms']}ms{mode_label}{rec_label}")

    await page.close()


# ---------------------------------------------------------------------------
# SAVE RESULTS
# ---------------------------------------------------------------------------
CSV_COLS = [
    "id", "url", "url_used", "domain", "status",
    "title", "authority", "description", "deadline", "pub_date",
    "proc_type", "cpv", "location", "ref_num", "contact",
    "model_used", "llm_tokens", "llm_cost",
    "downloaded_docs", "url_recovery", "err", "ms", "ts",
]

def save_results(results, output_json):
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    csv_out = output_json.replace(".json", ".csv")
    with open(csv_out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
        w.writeheader()
        for rec in results:
            row = dict(rec)
            row["downloaded_docs"] = ";".join(rec.get("downloaded_docs") or [])
            w.writerow(row)

    return csv_out


# ---------------------------------------------------------------------------
# PRINT SUMMARY
# ---------------------------------------------------------------------------
def print_summary(results, use_llm, download_docs):
    t   = len(results) or 1
    ok  = sum(1 for x in results if x["status"] == "success")
    err = sum(1 for x in results if x["status"] == "error")
    to  = sum(1 for x in results if x["status"] == "timeout")
    inv = sum(1 for x in results if x["status"] == "invalid")
    exp = sum(1 for x in results if x["status"] == "expired")
    avg = sum(x["ms"] for x in results) / t
    total_docs = sum(len(x.get("downloaded_docs") or []) for x in results)
    recovered  = sum(1 for x in results if x.get("url_recovery"))

    mode_label = "Phase 2 - LLM" if use_llm else "Phase 1 - XPath"
    print(f"\n{'='*62}")
    print(f"  RESULTS ({mode_label})")
    print(f"{'='*62}")
    print(f"  total:          {t}")
    print(f"  success:        {ok}  ({100*ok/t:.1f}%)")
    print(f"  errors:         {err}  ({100*err/t:.1f}%)")
    print(f"  expired (dead): {exp}  ({100*exp/t:.1f}%)")
    print(f"  timeouts:       {to}  ({100*to/t:.1f}%)")
    print(f"  invalid:        {inv}  ({100*inv/t:.1f}%)")
    print(f"  URL recovered:  {recovered}  ({100*recovered/t:.1f}%)")
    print(f"  avg time:       {avg:.0f}ms/url")
    if download_docs:
        print(f"  docs saved:     {total_docs}")

    if stats["url_recoveries"]:
        print(f"\n  URL RECOVERY BREAKDOWN:")
        for strategy, count in sorted(stats["url_recoveries"].items(), key=lambda x: -x[1]):
            print(f"    {strategy:25s}: {count}")

    print(f"{'='*62}")

    if use_llm and stats["total_calls"]:
        print(f"\n  LLM STATS:")
        print(f"    api calls:     {stats['total_calls']}")
        print(f"    retries:       {stats['retries']}")
        print(f"    total tokens:  {stats['total_tokens']:,}")
        print(f"    total cost:    ${stats['total_cost']:.4f}")
        print(f"    avg tok/call:  {stats['total_tokens']//stats['total_calls']}")
        print(f"    models used:")
        for m, c in stats["model_usage"].items():
            print(f"      {m}: {c} calls")
        print(f"{'='*62}")

    dom_stats = {}
    for x in results:
        d = x["domain"]
        dom_stats.setdefault(d, [0, 0])
        dom_stats[d][1] += 1
        if x["status"] == "success":
            dom_stats[d][0] += 1

    print("\n  domains:")
    for d, (s, tot) in sorted(dom_stats.items(), key=lambda x: -x[1][1]):
        calls = stats["calls_per_domain"].get(d, 0)
        call_str = f"  calls: {calls}" if use_llm else ""
        print(f"    {d:48s} {s:>4}/{tot:<4} ({100*s/tot:.0f}%){call_str}")
    print()


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
async def main(args):
    use_llm = args.llm

    client = None
    if use_llm:
        try:
            from openai import OpenAI
        except ImportError:
            print("pip install openai"); exit(1)

        api_key = args.api_key or os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            print("Need API key: set OPENROUTER_API_KEY or --api-key"); exit(1)

        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)

        log.info(f"testing API with model: {MODEL_CHAIN[0]}")
        try:
            t = client.chat.completions.create(
                model=MODEL_CHAIN[0],
                messages=[{"role": "user", "content": "reply ok"}],
                max_tokens=5,
            )
            log.info(f"API ok: {t.choices[0].message.content or '(empty)'}")
        except Exception as e:
            print(f"API test failed: {e}"); exit(1)

    # load CSV
    rows = []
    with open(args.input, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            u = row.get("url", "").strip()
            if u:
                rows.append(row)
    log.info(f"{len(rows)} urls loaded from {args.input}")

    # filters
    before = len(rows)
    if args.skip_done:
        rows = [r for r in rows if r.get("state", "") not in ("COMPLETED",)]

    # always skip these states
    rows = [r for r in rows if r.get("state", "") not in ("UNSUPPORTED",)]

    # NOTE: we no longer skip FAILED rows – those are exactly the ones to recover

    # filter obvious junk non-tender pages
    junk = ["/login", "/register", "/auth", "/passwort", "/password",
            "/account", "/warenkorb"]
    rows = [r for r in rows if not any(j in r["url"].lower() for j in junk)]

    if len(rows) != before:
        log.info(f"filtered to {len(rows)} rows")

    if args.limit > 0:
        rows = rows[:args.limit]
        log.info(f"limited to {args.limit}")

    if not rows:
        print("nothing to scrape"); return

    # group by domain for tab reuse
    groups = {}
    for r in rows:
        d = urlparse(r["url"]).netloc.lower()
        groups.setdefault(d, []).append(r)

    for d, g in sorted(groups.items(), key=lambda x: -len(x[1])):
        log.info(f"    {d}: {len(g)}")

    if args.download_docs:
        os.makedirs(args.download_dir, exist_ok=True)
        log.info(f"  document download ON  →  {args.download_dir}/")

    results = []
    sem     = asyncio.Semaphore(min(args.workers, 10))
    prog    = {"n": 0}
    total   = len(rows)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("pip install playwright && playwright install chromium"); exit(1)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
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
            # accept all cookies by default via storage state
            accept_downloads=True,
        )

        tasks = [
            run_domain(d, g, results, sem, ctx, prog, total,
                       client, use_llm, args.download_docs, args.download_dir,
                       folder_by_company=args.folder_by_company)
            for d, g in groups.items()
        ]
        await asyncio.gather(*tasks)
        await browser.close()

    # save
    csv_path   = save_results(results, args.output)
    stats_path = args.output.replace(".json", "_stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    print_summary(results, use_llm, args.download_docs)
    log.info(f"done → {args.output}  {csv_path}  {stats_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="German procurement scraper v4 – with URL recovery + robust downloads")
    p.add_argument("-i", "--input",        default="publications_b.csv", help="input CSV")
    p.add_argument("-o", "--output",       default="results_v4.json",    help="output JSON")
    p.add_argument("-w", "--workers",      type=int, default=8,          help="parallel browser tabs")
    p.add_argument("-n", "--limit",        type=int, default=0,          help="max URLs (0=all)")
    p.add_argument("--llm",                action="store_true",          help="enable LLM extraction (Phase 2)")
    p.add_argument("--api-key",            default=None,                 help="OpenRouter API key")
    p.add_argument("--skip-done",          action="store_true",          help="skip already COMPLETED rows")
    p.add_argument("--download-docs",      action="store_true",          help="download tender documents")
    p.add_argument("--download-dir",       default="downloads",          help="folder for downloaded docs")
    p.add_argument("--folder-by-company",  action="store_true",          help="organise downloads into subfolders named after the contracting authority (company name)")
    args = p.parse_args()

    if not os.path.exists(args.input):
        print(f"file not found: {args.input}"); exit(1)

    asyncio.run(main(args))