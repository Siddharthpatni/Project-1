#!/usr/bin/env python3
# scraper_v3.py  –  unified Phase 1 + Phase 2 scraper
#
# Improvements over v1/v2:
#   • Consistent output schema (JSON + CSV, same fields in both phases)
#   • Smart document download: only project-related docs (tender docs, specs, etc.)
#   • Multi-model LLM with cheap fallback chain
#   • Human-like download tricks: session cookies, headers, retry, JS click buttons
#   • More reliable page scraping: retry on empty, scroll to load lazy content
#   • Unified result dict schema so both modes produce identical columns
#
# Usage:
#   Phase 1 (XPath only, no LLM):
#       python3 scraper_v3.py -i publications_b.csv -n 100
#
#   Phase 2 (LLM-assisted):
#       python3 scraper_v3.py -i publications_b.csv -n 100 --llm
#
#   Download tender documents:
#       python3 scraper_v3.py -i publications_b.csv --llm --download-docs
#
#   With custom API key:
#       python3 scraper_v3.py -i publications_b.csv --llm --api-key YOUR_KEY
#
# Needs:
#   pip install playwright openai && playwright install chromium

import asyncio, csv, json, logging, time, argparse, os, re, hashlib
from datetime import datetime
from urllib.parse import urlparse, urljoin
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[logging.FileHandler("scraper_v3.log"), logging.StreamHandler()],
)
log = logging.getLogger("s")

# ---------------------------------------------------------------------------
# MODELS  (ordered cheapest → best quality; we try the first, fall back on failure)
# Pricing reference (per million tokens):
#   gemini-2.5-flash-lite  → $0.10 in / $0.40 out   (fastest, cheapest)
#   gemini-2.5-flash       → $0.30 in / $2.50 out
#   mistral/mistral-small  → $0.10 in / $0.30 out   (good alt)
#   qwen/qwen3-14b         → $0.15 in / $0.60 out   (within budget)
# ---------------------------------------------------------------------------
MODEL_CHAIN = [
    "google/gemini-2.5-flash-lite",   # primary – very cheap
    "qwen/qwen3-14b",                  # fallback – still budget, good at extraction
]

# ---------------------------------------------------------------------------
# UNIFIED RESULT SCHEMA  –  every scraper mode returns these exact keys
# ---------------------------------------------------------------------------
def empty_result(row, domain):
    return {
        # identifiers
        "id":           row.get("id", ""),
        "url":          row.get("url", ""),
        "domain":       domain,
        # extraction
        "status":       "pending",       # success | error | timeout | invalid
        "title":        None,
        "authority":    None,
        "description":  None,
        "deadline":     None,
        "pub_date":     None,
        "proc_type":    None,            # Verfahrensart
        "cpv":          None,
        "location":     None,
        "ref_num":      None,
        "contact":      None,
        # metadata
        "model_used":   None,            # which LLM model (None for XPath phase)
        "llm_tokens":   0,
        "llm_cost":     0.0,
        "downloaded_docs": [],           # filenames saved
        "err":          None,
        "ms":           0,
        "ts":           "",
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
}

# ---------------------------------------------------------------------------
# COOKIE BANNER DISMISSAL
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
]

async def dismiss_cookies(page):
    for sel in COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=600):
                await btn.click()
                await page.wait_for_timeout(400)
                return True
        except:
            pass
    return False

# ---------------------------------------------------------------------------
# PAGE TEXT EXTRACTION  –  cleans whitespace, scrolls to load lazy content
# ---------------------------------------------------------------------------
async def get_page_text(page, max_chars=7000):
    # scroll to bottom to trigger lazy-loaded content
    try:
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(400)
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

    # if still short, wait a bit more (JS-heavy pages)
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
# GONE CHECK  –  detect expired / deleted pages
# ---------------------------------------------------------------------------
GONE_PHRASES = [
    "nicht mehr verfügbar", "nicht gefunden", "abgelaufen",
    "seite existiert nicht", "page not found",
    "vergabe wurde aufgehoben", "bekanntmachung wurde gelöscht",
    "kein ergebnis", "kein treffer", "404", "403 forbidden",
    "diese ausschreibung existiert nicht",
]

def is_gone(text):
    low = text.lower()[:6000]
    return any(p in low for p in GONE_PHRASES)

# ---------------------------------------------------------------------------
# XPATH SELECTORS  –  Phase 1 manual extraction
# ---------------------------------------------------------------------------
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

async def xpath_extract(page):
    """Try XPath extraction for all fields. Returns dict with found values."""
    out = {}
    for field, xps in XPATHS.items():
        val = await xpath_get(page, xps)
        if val:
            out[field] = val

    # fallback: grab all dt/dd and table label→value pairs
    if not out.get("title") and not out.get("authority"):
        try:
            for dt in await page.locator("xpath=//dt").all():
                label = (await dt.inner_text()).strip()
                value = await dt.evaluate("el => el.nextElementSibling?.textContent?.trim()")
                if label and value and len(label) < 150:
                    # map known labels
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
# LLM EXTRACTION  –  send visible text to LLM, get JSON back
# ---------------------------------------------------------------------------
LLM_PROMPT = """Extract procurement tender data from this German page text.
URL: {url}

PAGE TEXT:
{text}

Return ONLY valid JSON. No markdown, no backticks, no explanation.
Use null for missing fields.

{{"title":"tender title","authority":"Auftraggeber/Vergabestelle","description":"what is being procured (2-3 sentences max)","deadline":"Angebotsfrist/Teilnahmefrist date","pub_date":"Veröffentlichungsdatum","proc_type":"Verfahrensart","cpv":"CPV codes if present","location":"Erfüllungsort","ref_num":"Vergabenummer/Aktenzeichen","contact":"contact name/email/phone"}}"""

def extract_with_llm(client, page_text, url, domain, model_chain=None):
    """Try each model in chain, return (data, model_used, tokens, cost) or None."""
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

                tok = 0
                cost = 0.0
                if resp.usage:
                    tok = resp.usage.total_tokens or 0
                    stats["total_tokens"] += tok
                    stats["prompt_tokens"] += resp.usage.prompt_tokens or 0
                    stats["completion_tokens"] += resp.usage.completion_tokens or 0
                    if hasattr(resp.usage, 'cost') and resp.usage.cost:
                        cost = float(resp.usage.cost)
                        stats["total_cost"] += cost

                stats["model_usage"].setdefault(model, 0)
                stats["model_usage"][model] += 1

                raw = (resp.choices[0].message.content or "").strip()
                # strip markdown fences
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
                # if rate limit, try next model immediately
                if "rate" in msg.lower() or "429" in msg:
                    break
                time.sleep(0.5)

    return None, None, 0, 0.0

# ---------------------------------------------------------------------------
# DOCUMENT DOWNLOAD  –  smart, human-like, project-relevant only
# ---------------------------------------------------------------------------

# Extensions we want
DOC_EXTS = {".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".rar", ".7z", ".odt", ".ods"}

# Keywords in URL or link text that suggest it's a tender document
DOC_POSITIVE_KEYWORDS = [
    "unterlag", "anlage", "leistung", "vergabe", "ausschreibung",
    "dokument", "download", "attachment", "bidding", "tender",
    "specification", "specs", "lv_", "lvh_", "gaeb", "leistungsverzeichnis",
    "bekanntmachung", "vertrag", "vertrag", "formular",
]

# Keywords that indicate NOT a tender doc (generic site docs we skip)
DOC_NEGATIVE_KEYWORDS = [
    "agb", "datenschutz", "impressum", "nutzungsbedingungen", "hilfe",
    "handbuch", "anleitung", "tutorial", "logo", "favicon",
    "stylesheet", "font", "newsletter", "broschüre", "flyer",
]

def is_relevant_doc(href, link_text, url):
    """Decide if a link is likely a tender-related document."""
    lower_href = href.lower()
    lower_text = (link_text or "").lower()
    path = urlparse(href).path.lower()

    # negative filter first
    if any(k in lower_href or k in lower_text for k in DOC_NEGATIVE_KEYWORDS):
        return False

    ext = Path(path).suffix
    has_doc_ext = ext in DOC_EXTS

    # positive: known extension
    if has_doc_ext:
        # still skip if clearly not a tender doc
        return True

    # positive: URL or text contains procurement keywords
    if any(k in lower_href or k in lower_text for k in DOC_POSITIVE_KEYWORDS):
        return True

    # positive: download-like URL patterns without extension
    if re.search(r'/(download|file|dokument|unterlage|attachment)[s/]', lower_href):
        return True

    return False


async def click_download_buttons(page):
    """
    Human trick: some portals hide docs behind JS buttons (e.g. "Unterlagen herunterladen").
    We click them to reveal the actual download links or trigger browser downloads.
    """
    trigger_texts = [
        "Unterlagen", "Dokumente", "Download", "herunterladen",
        "Vergabeunterlagen", "Angebots", "Teilnahme",
    ]
    for txt in trigger_texts:
        try:
            btn = page.locator(f"xpath=//button[contains(.,'{txt}')] | //a[contains(.,'{txt}')]").first
            if await btn.is_visible(timeout=500):
                await btn.click()
                await page.wait_for_timeout(800)
        except:
            pass


async def download_documents(page, tender_id, base_url, download_dir, max_docs=20):
    """
    Find and download all project-relevant documents from the page.
    Uses multiple human-like tricks:
      1. Scan all <a href> links
      2. Try clicking JS download buttons to reveal hidden links
      3. Try common portal-specific download URL patterns
      4. Respect session cookies (uses page.context.request)
    Returns list of saved filenames.
    """
    saved = []
    seen_urls = set()

    folder = os.path.join(download_dir, re.sub(r'[^\w\-]', '_', str(tender_id))[:60])
    os.makedirs(folder, exist_ok=True)

    async def fetch_and_save(download_url, suggested_name=None):
        if download_url in seen_urls or len(saved) >= max_docs:
            return
        seen_urls.add(download_url)

        try:
            # use page context so session cookies are included
            response = await page.context.request.get(
                download_url,
                timeout=20000,
                headers={
                    "Accept": "application/pdf,application/octet-stream,*/*",
                    "Referer": base_url,
                }
            )

            if response.status >= 400:
                return

            content_type = response.headers.get("content-type", "").lower()
            # skip HTML responses (login walls, error pages)
            if "text/html" in content_type and not download_url.lower().endswith(".pdf"):
                return

            # determine filename
            cd = response.headers.get("content-disposition", "")
            filename = ""
            if "filename*=" in cd:
                # RFC 5987 encoded filename (e.g.  filename*=UTF-8''Leistungsverzeichnis.pdf)
                m = re.search(r"filename\*=(?:UTF-8'')?([^\s;]+)", cd, re.I)
                if m:
                    from urllib.parse import unquote
                    filename = unquote(m.group(1))
            if not filename and "filename=" in cd:
                m = re.search(r'filename=["\']?([^"\';\r\n]+)', cd)
                if m:
                    filename = m.group(1).strip("\"' ")
            if not filename and suggested_name:
                filename = suggested_name
            if not filename:
                path_part = urlparse(download_url).path
                filename = path_part.split("/")[-1].split("?")[0]
            if not filename or filename in ("download", "document", "file", ""):
                # guess extension from content-type
                ext_map = {"pdf":"pdf","zip":"zip","msword":"doc","vnd.openxmlformats":"docx"}
                ext = "bin"
                for k, v in ext_map.items():
                    if k in content_type:
                        ext = v; break
                filename = f"doc_{len(saved)+1}.{ext}"

            filename = re.sub(r'[^\w.\-]', '_', filename)[:120]
            dest = os.path.join(folder, filename)

            if os.path.exists(dest):
                saved.append(filename)
                return

            body = await response.body()
            if len(body) < 100:   # skip empty/near-empty files
                return

            with open(dest, "wb") as fh:
                fh.write(body)
            saved.append(filename)
            log.info(f"    ↓ {filename}  ({len(body)//1024}KB)")

        except Exception as e:
            log.debug(f"    download failed {download_url}: {str(e)[:80]}")

    # --- Pass 1: scan all existing links on the page ---
    try:
        links = await page.locator("xpath=//a[@href]").all()
        for link in links:
            try:
                href = await link.get_attribute("href")
                if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                    continue
                full_url = urljoin(base_url, href)
                text = await link.inner_text()
                if is_relevant_doc(full_url, text, base_url):
                    await fetch_and_save(full_url)
            except:
                pass
    except:
        pass

    # --- Pass 2: click JS buttons to reveal hidden download links ---
    if len(saved) < 3:   # only do this if we haven't found much yet
        try:
            await click_download_buttons(page)
            await page.wait_for_timeout(1000)
            # scan links again after clicking
            links = await page.locator("xpath=//a[@href]").all()
            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if not href or href.startswith(("javascript:", "mailto:", "tel:", "#")):
                        continue
                    full_url = urljoin(base_url, href)
                    if full_url in seen_urls:
                        continue
                    text = await link.inner_text()
                    if is_relevant_doc(full_url, text, base_url):
                        await fetch_and_save(full_url)
                except:
                    pass
        except:
            pass

    # --- Pass 3: try common portal-specific download patterns ---
    # Some portals have predictable API endpoints for documents
    portal_patterns = []
    parsed = urlparse(base_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # evergabe pattern
    if "evergabe" in parsed.netloc:
        m = re.search(r'/tender/(\d+)', parsed.path)
        if m:
            tid = m.group(1)
            portal_patterns.append(f"{base}/tender/{tid}/documents")
            portal_patterns.append(f"{base}/api/tender/{tid}/documents")

    # subreport pattern
    if "subreport" in parsed.netloc:
        m = re.search(r'id=(\d+)', parsed.query)
        if m:
            portal_patterns.append(f"{base}/dokumente.aspx?id={m.group(1)}")

    for pattern_url in portal_patterns:
        if pattern_url not in seen_urls:
            await fetch_and_save(pattern_url)

    return saved

# ---------------------------------------------------------------------------
# SKIP PATTERNS  –  URLs we know are not tender detail pages
# ---------------------------------------------------------------------------
SKIP_URL_PATTERNS = [
    "/login", "/register", "/auth", "/unterlagen", "zustellweg",
    "/passwort", "/password", "/account", "/warenkorb", "/cart",
    "/impressum", "/datenschutz", "/agb", "/hilfe",
]

def should_skip_url(url):
    low = url.lower()
    return any(p in low for p in SKIP_URL_PATTERNS)

# ---------------------------------------------------------------------------
# SCRAPE ONE URL  –  unified for both XPath and LLM mode
# ---------------------------------------------------------------------------
async def scrape_one(page, row, client=None, use_llm=False, download_docs=False, download_dir="downloads"):
    url = row.get("url", "").strip()
    domain = urlparse(url).netloc.lower()
    r = empty_result(row, domain)
    t0 = time.time()

    try:
        # fast skip known-bad URLs
        if should_skip_url(url):
            r["status"] = "invalid"; r["err"] = "non-tender URL"
            return r

        # load page
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=10000)

        if resp and resp.status >= 400:
            r["status"] = "invalid"; r["err"] = f"HTTP {resp.status}"
            return r

        await page.wait_for_timeout(600)
        await dismiss_cookies(page)

        # get visible text (also scrolls to trigger lazy load)
        page_text = await get_page_text(page)

        if not page_text or len(page_text) < 50:
            r["status"] = "error"; r["err"] = "empty page"
            return r

        if is_gone(page_text):
            r["status"] = "invalid"; r["err"] = "tender no longer available"
            return r

        # ---- extraction ----
        if use_llm and client:
            data, model_used, tok, cost = extract_with_llm(client, page_text, url, domain)
            r["model_used"] = model_used
            r["llm_tokens"] = tok
            r["llm_cost"] = cost

            if data:
                r["title"]       = data.get("title")
                r["authority"]   = data.get("authority")
                r["description"] = data.get("description")
                r["deadline"]    = data.get("deadline")
                r["pub_date"]    = data.get("pub_date")
                r["proc_type"]   = data.get("proc_type")
                r["cpv"]         = data.get("cpv")
                r["location"]    = data.get("location")
                r["ref_num"]     = data.get("ref_num")
                r["contact"]     = data.get("contact")

            # if LLM failed or got nothing useful, fall back to XPath
            if not r["title"] and not r["authority"]:
                xpath_data = await xpath_extract(page)
                for k, v in xpath_data.items():
                    if not r.get(k):
                        r[k] = v
                if r["title"] or r["authority"]:
                    r["model_used"] = "xpath_fallback"

        else:
            # Phase 1: pure XPath
            xpath_data = await xpath_extract(page)
            for k, v in xpath_data.items():
                r[k] = v

        # ---- status ----
        if r["title"] or r["authority"]:
            r["status"] = "success"
        else:
            r["status"] = "error"; r["err"] = "nothing extracted"

        # ---- document download ----
        if download_docs and r["status"] == "success":
            tender_id = r["id"] or re.sub(r'[^\w]', '_', url[-40:])
            docs = await download_documents(page, tender_id, url, download_dir)
            r["downloaded_docs"] = docs
            if docs:
                log.info(f"    saved {len(docs)} doc(s) for {str(tender_id)[:20]}")

    except Exception as e:
        err_msg = str(e)
        if "timeout" in err_msg.lower() or "Timeout" in err_msg:
            r["status"] = "timeout"; r["err"] = "page timed out (10s)"
        else:
            r["status"] = "error"; r["err"] = err_msg[:300]

    r["ms"] = int((time.time() - t0) * 1000)
    r["ts"] = datetime.now().isoformat()
    return r

# ---------------------------------------------------------------------------
# BATCH  –  one persistent browser tab per domain
# ---------------------------------------------------------------------------
async def run_domain(domain, rows, results, sem, ctx, prog, total, client, use_llm, download_docs, download_dir):
    log.info(f"  {domain}  ({len(rows)} urls)")
    page = await ctx.new_page()

    for row in rows:
        async with sem:
            rec = await scrape_one(page, row, client=client, use_llm=use_llm,
                                   download_docs=download_docs, download_dir=download_dir)
            results.append(rec)
            prog["n"] += 1
            n, tot = prog["n"], total
            icon = "✓" if rec["status"] == "success" else ("⏱" if rec["status"] == "timeout" else "✗")
            mode = f" [{rec['model_used']}]" if rec.get("model_used") else ""
            log.info(f"  {icon} [{n}/{tot} {100*n/tot:.1f}%] {domain} {rec['status']} {rec['ms']}ms{mode}")

    await page.close()

# ---------------------------------------------------------------------------
# SAVE RESULTS  –  JSON + CSV with consistent schema
# ---------------------------------------------------------------------------
CSV_COLS = [
    "id", "url", "domain", "status",
    "title", "authority", "description", "deadline", "pub_date",
    "proc_type", "cpv", "location", "ref_num", "contact",
    "model_used", "llm_tokens", "llm_cost",
    "downloaded_docs", "err", "ms", "ts",
]

def save_results(results, output_json):
    # JSON
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # CSV  (downloaded_docs list → semicolon-joined string)
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
    t = len(results) or 1
    ok  = sum(1 for x in results if x["status"] == "success")
    err = sum(1 for x in results if x["status"] == "error")
    to  = sum(1 for x in results if x["status"] == "timeout")
    inv = sum(1 for x in results if x["status"] == "invalid")
    avg = sum(x["ms"] for x in results) / t
    total_docs = sum(len(x.get("downloaded_docs") or []) for x in results)

    mode_label = "Phase 2 - LLM" if use_llm else "Phase 1 - XPath"
    print(f"\n{'='*58}")
    print(f"  RESULTS ({mode_label})")
    print(f"{'='*58}")
    print(f"  total:        {t}")
    print(f"  success:      {ok}  ({100*ok/t:.1f}%)")
    print(f"  errors:       {err}  ({100*err/t:.1f}%)")
    print(f"  timeouts:     {to}  ({100*to/t:.1f}%)")
    print(f"  invalid:      {inv}  ({100*inv/t:.1f}%)")
    print(f"  avg time:     {avg:.0f}ms/url")
    if download_docs:
        print(f"  docs saved:   {total_docs}")
    print(f"{'='*58}")

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
        print(f"{'='*58}")

    # per-domain
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
        print(f"    {d:45s} {s:>4}/{tot:<4} ({100*s/tot:.0f}%){call_str}")
    print()

# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
async def main(args):
    use_llm = args.llm

    # setup LLM client if needed
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

        # quick test
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
    rows = [r for r in rows if r.get("state", "") not in ("FAILED", "UNSUPPORTED")]
    if args.skip_done:
        rows = [r for r in rows if r.get("state", "") != "COMPLETED"]
    junk = ["unterlagen", "zustellweg", "/login", "/register", "/auth",
            "/passwort", "/password", "/account", "/warenkorb"]
    rows = [r for r in rows if not any(j in r["url"].lower() for j in junk)]
    if len(rows) != before:
        log.info(f"filtered to {len(rows)} rows")

    if args.limit > 0:
        rows = rows[:args.limit]
        log.info(f"limited to {args.limit}")

    if not rows:
        print("nothing to scrape"); return

    # group by domain
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
    sem = asyncio.Semaphore(min(args.workers, 10))
    prog = {"n": 0}
    total = len(rows)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("pip install playwright && playwright install chromium"); exit(1)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                "--disable-extensions",
                "--blink-settings=imagesEnabled=false",  # faster
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
        )

        tasks = [
            run_domain(d, g, results, sem, ctx, prog, total,
                       client, use_llm, args.download_docs, args.download_dir)
            for d, g in groups.items()
        ]
        await asyncio.gather(*tasks)
        await browser.close()

    # save
    csv_path = save_results(results, args.output)
    stats_path = args.output.replace(".json", "_stats.json")
    with open(stats_path, "w") as f:
        json.dump(stats, f, indent=2)

    print_summary(results, use_llm, args.download_docs)
    log.info(f"done → {args.output}  {csv_path}  {stats_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="German procurement scraper v3 (unified)")
    p.add_argument("-i", "--input",        default="publications_b.csv", help="input CSV")
    p.add_argument("-o", "--output",       default="results_v3.json",    help="output JSON")
    p.add_argument("-w", "--workers",      type=int, default=8,          help="parallel tabs")
    p.add_argument("-n", "--limit",        type=int, default=0,          help="max URLs (0=all)")
    p.add_argument("--llm",                action="store_true",          help="enable LLM extraction (Phase 2)")
    p.add_argument("--api-key",            default=None,                 help="OpenRouter API key")
    p.add_argument("--skip-done",          action="store_true",          help="skip COMPLETED rows")
    p.add_argument("--download-docs",      action="store_true",          help="download tender documents")
    p.add_argument("--download-dir",       default="downloads",          help="folder for downloaded docs")
    args = p.parse_args()

    if not os.path.exists(args.input):
        print(f"file not found: {args.input}"); exit(1)

    asyncio.run(main(args))