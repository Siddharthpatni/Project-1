# scraper.py
# Phase 1 - Manual scraping of German procurement portals
# Uses Playwright (browser automation) + XPath (HTML element selectors)
# Run: python3 scraper.py --input publications_b.csv --limit 100

import asyncio
import csv
import json
import logging
import time
import argparse
import os
import re
import urllib.request
from datetime import datetime
from urllib.parse import urlparse, urljoin
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout

# basic logging - goes to file and terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("scraper")


# -------------------------------------------------------------------
# XPATH SELECTORS
# XPath lets us find specific elements on a web page using a path-like
# syntax. Example:  //h1  →  finds the first <h1> tag on the page
#
# We define common German procurement labels here and try multiple
# variants because each portal structures its HTML differently.
# -------------------------------------------------------------------

# tries each xpath in order, returns the text of the first one that works
async def get_text(page, xpaths):
    for xp in xpaths:
        try:
            els = await page.locator(f"xpath={xp}").all()
            if els:
                txt = (await els[0].inner_text()).strip()
                if txt and len(txt) < 2000:
                    return txt
        except Exception:
            pass
    return None


# generic german procurement labels that appear on almost every portal
TITLE_XP = [
    "//h1",
    "//*[contains(@class,'title') and (self::h1 or self::h2)]",
    "//title",
]
AUTHORITY_XP = [
    "//dt[contains(.,'Auftraggeber')]/following-sibling::dd[1]",
    "//th[contains(.,'Auftraggeber')]/following-sibling::td[1]",
    "//td[contains(.,'Auftraggeber')]/following-sibling::td[1]",
    "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
    "//*[contains(text(),'Vergabestelle')]/following-sibling::*[1]",
]
DEADLINE_XP = [
    "//dt[contains(.,'Angebotsfrist') or contains(.,'Frist')]/following-sibling::dd[1]",
    "//th[contains(.,'Frist')]/following-sibling::td[1]",
    "//td[contains(.,'Frist')]/following-sibling::td[1]",
    "//*[contains(text(),'Angebotsfrist') or contains(text(),'Teilnahmefrist')]/following-sibling::*[1]",
    "//*[contains(text(),'Frist')]/following-sibling::*[1]",
]
PUBDATE_XP = [
    "//dt[contains(.,'Veröffentlich')]/following-sibling::dd[1]",
    "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
    "//*[contains(text(),'Bekanntmachung')]/following-sibling::*[1]",
]
TYPE_XP = [
    "//dt[contains(.,'Verfahrensart') or contains(.,'Vergabeart')]/following-sibling::dd[1]",
    "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
]
CPV_XP = [
    "//*[contains(text(),'CPV')]/following-sibling::*[1]",
    "//dt[contains(.,'CPV')]/following-sibling::dd[1]",
]
LOCATION_XP = [
    "//*[contains(text(),'Erfüllungsort') or contains(text(),'Ort der Leistung')]/following-sibling::*[1]",
]
REF_XP = [
    "//dt[contains(.,'Vergabenummer') or contains(.,'Aktenzeichen')]/following-sibling::dd[1]",
    "//*[contains(text(),'Vergabenummer') or contains(text(),'Aktenzeichen')]/following-sibling::*[1]",
]
DESC_XP = [
    "//*[contains(text(),'Beschreibung') or contains(text(),'Leistung')]/following-sibling::*[1]",
    "//*[contains(@class,'description')]",
]
CONTACT_XP = [
    "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
    "//*[contains(@class,'contact')]",
]


# -------------------------------------------------------------------
# DOMAIN CONFIGS
# Because each portal has slightly different HTML, we try portal-specific
# xpaths first, then fall back to the generic ones above.
# -------------------------------------------------------------------

# helper so each domain config is just the extra specific xpaths
def make_selectors(extra_title=None, extra_auth=None, extra_deadline=None):
    return {
        "title":                 (extra_title or []) + TITLE_XP,
        "contracting_authority": (extra_auth or []) + AUTHORITY_XP,
        "description":           DESC_XP,
        "deadline":              (extra_deadline or []) + DEADLINE_XP,
        "publication_date":      PUBDATE_XP,
        "tender_type":           TYPE_XP,
        "cpv_codes":             CPV_XP,
        "location":              LOCATION_XP,
        "reference_number":      REF_XP,
        "contact_info":          CONTACT_XP,
    }


DOMAINS = {
    "www.evergabe.de": {
        "wait": "//h1 | //div[contains(@class,'content')]",
        "sel":  make_selectors(extra_auth=["//*[contains(@class,'vergabestelle')]"]),
    },
    "www.subreport.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel":  make_selectors(
            extra_title=["//div[contains(@class,'bekanntmachungstitel')]"],
            extra_auth=["//span[contains(@id,'lblVergabestelle') or contains(@id,'lblAuftraggeber')]"],
            extra_deadline=["//span[contains(@id,'lblAngebotsfrist')]"],
        ),
    },
    "vergabemarktplatz.brandenburg.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel":  make_selectors(extra_auth=["//*[contains(@class,'organisation-name')]"]),
    },
    "vergabe.niedersachsen.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel":  make_selectors(),
    },
    "bieterzugang.deutsche-evergabe.de": {
        "wait": "//div | //h1",
        "sel":  make_selectors(),
    },
    "www.evergabe.nrw.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel":  make_selectors(),
    },
    "www.vergabe-westfalen.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel":  make_selectors(),
    },
    "www.deutsches-ausschreibungsblatt.de": {
        "wait": "//div[contains(@class,'content')]",
        "sel":  make_selectors(extra_auth=["//td[contains(text(),'Auftraggeber')]/following-sibling::td[1]"]),
    },
    "www.had.de": {
        "wait": "//div[contains(@class,'content')]",
        "sel":  make_selectors(
            extra_auth=["//td[contains(text(),'Auftraggeber')]/following-sibling::td[1]"],
            extra_deadline=["//td[contains(text(),'Frist') or contains(text(),'Abgabetermin')]/following-sibling::td[1]"],
        ),
    },
    "www.vergabe.metropoleruhr.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel":  make_selectors(),
    },
    "fbhh-evergabe.web.hamburg.de": {
        "wait": "//div | //h1",
        "sel":  make_selectors(),
    },
    "bi-medien.de": {
        "wait": "//div[contains(@class,'content')]",
        "sel":  make_selectors(extra_auth=["//span[contains(@class,'auftraggeber')]"]),
    },
    "www.tender24.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel":  make_selectors(
            extra_auth=["//span[@id='lblVergabestelle']"],
            extra_deadline=["//span[@id='lblAngebotsfrist']"],
        ),
    },
    "vergabe.landbw.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel":  make_selectors(),
    },
    "www.vergabe24.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel":  make_selectors(extra_auth=["//span[@id='lblVergabestelle']"]),
    },
    "vergabekooperation.berlin": {
        "wait": "//div[contains(@class,'detail')]",
        "sel":  make_selectors(),
    },
    "www.evergabe.bayern.de": {
        "wait": "//div | //h1",
        "sel":  make_selectors(),
    },
    "vergabeportal-bw.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel":  make_selectors(),
    },
    "vergabe.fraunhofer.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel":  make_selectors(),
    },
    "www.ausschreibungen.ls.brandenburg.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel":  make_selectors(),
    },
    "landesverwaltung.vergabe.rlp.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel":  make_selectors(),
    },
    "lbb.vergabe.rlp.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel":  make_selectors(),
    },
    "vergabe.deges.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel":  make_selectors(),
    },
    "www.evergabe.sachsen.de": {
        "wait": "//div[contains(@class,'detail')]",
        "sel":  make_selectors(),
    },
    "www.vergabe.metropoleruhr.de": {
        "wait": "//div[contains(@class,'notice')]",
        "sel":  make_selectors(),
    },
    "vergabe.muenchen.de": {
        "wait": "//div | //h1",
        "sel":  make_selectors(),
    },
    "vergabe.bremen.de": {
        "wait": "//div | //h1",
        "sel":  make_selectors(),
    },
}

# anything not listed above gets this fallback
FALLBACK = {
    "wait": "//body",
    "sel":  make_selectors(),
}


def get_config(url):
    domain = urlparse(url).netloc.lower()
    if domain in DOMAINS:
        return domain, DOMAINS[domain]
    # partial match for subdomains etc.
    for key in DOMAINS:
        if key in domain or domain in key:
            return domain, DOMAINS[key]
    return domain, FALLBACK


# -------------------------------------------------------------------
# COOKIE BANNER DISMISSAL
# Most German sites show a GDPR cookie popup. We try to click "accept"
# so it doesn't cover the actual content we want to scrape.
# -------------------------------------------------------------------

async def dismiss_cookies(page):
    buttons = [
        "xpath=//button[contains(text(),'Akzeptieren')]",
        "xpath=//button[contains(text(),'Alle akzeptieren')]",
        "xpath=//button[contains(text(),'Accept')]",
        "xpath=//button[contains(text(),'Zustimmen')]",
        "xpath=//button[contains(text(),'Nur notwendige')]",
        "xpath=//button[contains(@class,'accept') or contains(@class,'consent')]",
        "xpath=//button[@id='accept' or @id='acceptCookies']",
    ]
    for sel in buttons:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await page.wait_for_timeout(500)
                return
        except Exception:
            pass


# -------------------------------------------------------------------
# FALLBACK DATA EXTRACTION
# If our specific XPaths don't find anything, we grab ALL label→value
# pairs from <dt>/<dd> lists and <table> rows on the page.
# This is a safety net so we still capture something from unknown layouts.
# -------------------------------------------------------------------

async def grab_all_labels(page):
    data = {}
    try:
        # definition lists  (<dt>label</dt><dd>value</dd>)
        for dt in await page.locator("xpath=//dt").all():
            try:
                label = (await dt.inner_text()).strip()
                value = await dt.evaluate("el => el.nextElementSibling?.textContent?.trim()")
                if label and value and len(label) < 150:
                    data[label] = value
            except Exception:
                pass

        # table rows  (<td>label</td><td>value</td>)
        for row in await page.locator("xpath=//tr").all():
            try:
                cells = await row.locator("td, th").all()
                if len(cells) >= 2:
                    label = (await cells[0].inner_text()).strip()
                    value = (await cells[1].inner_text()).strip()
                    if label and value and len(label) < 150:
                        data[label] = value
            except Exception:
                pass
    except Exception:
        pass
    return data


# -------------------------------------------------------------------
# DOCUMENT DOWNLOAD
# After a page is scraped, we look for any downloadable files linked
# on the page (PDFs, ZIPs, Word docs etc.) and save them locally.
# Files go into:  downloads/<tender_id>/<filename>
# -------------------------------------------------------------------

# file extensions we want to download
DOC_EXTENSIONS = (".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".rar", ".7z")

async def download_documents(page, tender_id, base_url, download_dir):
    """
    Finds all download links on the current page and saves the files.
    Returns a list of filenames that were saved.
    """
    saved = []

    try:
        # grab every <a href> on the page
        links = await page.locator("xpath=//a[@href]").all()
        seen  = set()  # avoid downloading the same file twice

        for link in links:
            try:
                href = await link.get_attribute("href")
                if not href:
                    continue

                # make absolute URL
                full_url = urljoin(base_url, href)

                # only download known document types
                lower = full_url.lower().split("?")[0]  # strip query params for extension check
                if not any(lower.endswith(ext) for ext in DOC_EXTENSIONS):
                    continue

                if full_url in seen:
                    continue
                seen.add(full_url)

                # build save path:  downloads/<tender_id>/<filename>
                raw_name = full_url.split("/")[-1].split("?")[0] or "document"
                # sanitize filename - remove anything sketchy
                filename  = re.sub(r'[^\w.\-]', '_', raw_name)[:100]
                folder    = os.path.join(download_dir, str(tender_id))
                os.makedirs(folder, exist_ok=True)
                dest      = os.path.join(folder, filename)

                # skip if already downloaded
                if os.path.exists(dest):
                    saved.append(filename)
                    continue

                # try to download the file
                try:
                    req = urllib.request.Request(
                        full_url,
                        headers={"User-Agent": "Mozilla/5.0 (compatible; scraper/1.0)"},
                    )
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        with open(dest, "wb") as fh:
                            fh.write(resp.read())
                    saved.append(filename)
                    log.info(f"    ↓ downloaded: {filename}")
                except Exception as dl_err:
                    log.debug(f"    skip {filename}: {dl_err}")

            except Exception:
                pass

    except Exception:
        pass

    return saved


# -------------------------------------------------------------------
# SCRAPE ONE URL
# This is the main function. For each URL we:
#   1. Load the page in the browser
#   2. Dismiss cookie popup
#   3. Try our XPath selectors for each field
#   4. Fall back to grabbing all label/value pairs
#   5. Download any found documents (if --download-docs is set)
#   6. Return a dict with everything we found
# -------------------------------------------------------------------

# words that signal a tender was deleted / page doesn't exist
EXPIRED_WORDS = [
    "nicht mehr verfügbar", "nicht gefunden", "abgelaufen",
    "Seite existiert nicht", "Page not found",
    "Vergabe wurde aufgehoben", "Bekanntmachung wurde gelöscht",
    "kein Ergebnis", "Kein Treffer",
]


async def scrape_url(page, row, config, download_docs=False, download_dir="downloads"):
    url    = row["url"]
    domain, cfg = get_config(url)

    result = {
        "id":         row.get("id", ""),
        "url":        url,
        "domain":     domain,
        "row_state":  row.get("state", ""),
        "status":     "pending",
        "title":      None,
        "contracting_authority": None,
        "description":     None,
        "deadline":        None,
        "publication_date":None,
        "tender_type":     None,
        "cpv_codes":       None,
        "location":        None,
        "reference_number":None,
        "contact_info":    None,
        "extra_fields":    {},
        "downloaded_docs": [],   # filenames of any documents saved from this page
        "error_message":   None,
        "scrape_time_ms":  0,
        "scraped_at":      "",
    }

    t_start = time.time()

    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=20000)

        # 404 or similar
        if resp and resp.status >= 400:
            result["status"] = "invalid"
            result["error_message"] = f"HTTP {resp.status}"
            return result

        # give JS a moment to render
        await page.wait_for_timeout(1500)
        await dismiss_cookies(page)

        # wait for the main content selector (best effort)
        try:
            await page.wait_for_selector(f"xpath={cfg['wait']}", timeout=5000)
        except PlaywrightTimeout:
            pass  # continue anyway, page might still be useful

        # check if the tender was deleted / page is gone
        try:
            body = await page.inner_text("body")
            for word in EXPIRED_WORDS:
                if word.lower() in body.lower()[:5000]:
                    result["status"] = "invalid"
                    result["error_message"] = f"Page removed ({word})"
                    return result
        except Exception:
            pass

        # extract each field using our XPath lists
        for field, xpaths in cfg["sel"].items():
            val = await get_text(page, xpaths)
            if val:
                result[field] = val

        # fallback: grab everything we can find
        result["extra_fields"] = await grab_all_labels(page)

        # download any linked documents if the flag is on
        if download_docs:
            tender_id = result["id"] or re.sub(r'[^\w]', '_', url[-40:])
            result["downloaded_docs"] = await download_documents(
                page, tender_id, url, download_dir
            )
            if result["downloaded_docs"]:
                log.info(f"    saved {len(result['downloaded_docs'])} doc(s) for {tender_id[:20]}")

        # decide overall status
        if result["title"] or result["contracting_authority"] or result["extra_fields"]:
            result["status"] = "success"
        else:
            result["status"] = "error"
            result["error_message"] = "Nothing extracted"

    except PlaywrightTimeout:
        result["status"] = "timeout"
        result["error_message"] = "Page load timed out (20s)"
    except Exception as e:
        result["status"] = "error"
        result["error_message"] = str(e)[:300]

    result["scrape_time_ms"] = int((time.time() - t_start) * 1000)
    result["scraped_at"]     = datetime.now().isoformat()
    return result


# -------------------------------------------------------------------
# BATCH - process all URLs for one domain using one persistent tab
# Reusing the same tab across URLs on the same domain is faster than
# opening a new tab for every URL.
# -------------------------------------------------------------------

async def run_domain(domain, rows, cfg, results, sem, ctx, counter, total, download_docs=False, download_dir="downloads"):
    log.info(f"  starting {domain}  ({len(rows)} urls)")
    page = await ctx.new_page()

    for i, row in enumerate(rows):
        async with sem:
            rec = await scrape_url(page, row, cfg, download_docs, download_dir)
            results.append(rec)
            counter["n"] += 1
            icon = "✓" if rec["status"] == "success" else ("⏱" if rec["status"] == "timeout" else "✗")
            log.info(
                f"  {icon} [{counter['n']}/{total}  {100*counter['n']/total:.1f}%]  "
                f"{domain}  {rec['status']}  {rec['scrape_time_ms']}ms"
            )

    await page.close()
    log.info(f"  done: {domain}")


# -------------------------------------------------------------------
# MAIN ORCHESTRATION
# Loads URLs, groups them by domain, then runs all domain batches
# concurrently using Python's asyncio (async/await).
# -------------------------------------------------------------------

async def run(input_file, output_file, workers, skip_completed, limit, download_docs=False, download_dir="downloads"):
    # ---------------------------------------------------------------
    # CSV LOADING  ← this is where publications_b.csv is read
    # The CSV must have at minimum a 'url' column.
    # Other columns (id, state, domain, error) are optional extras.
    # ---------------------------------------------------------------
    rows = []
    with open(input_file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("url", "").strip():
                rows.append(row)
    log.info(f"loaded {len(rows)} urls from {input_file}")

    # skip already-done if asked
    if skip_completed:
        before = len(rows)
        rows = [r for r in rows if r.get("state", "") != "COMPLETED"]
        log.info(f"skipped {before - len(rows)} completed rows  ({len(rows)} left)")

    # cap total if asked
    if limit and limit > 0:
        rows = rows[:limit]
        log.info(f"limited to first {limit} urls")

    # group by domain so we reuse one tab per domain
    groups = {}
    for r in rows:
        d = urlparse(r["url"]).netloc.lower()
        groups.setdefault(d, []).append(r)
    for d, g in sorted(groups.items(), key=lambda x: -len(x[1])):
        log.info(f"    {d}: {len(g)}")

    results = []
    sem     = asyncio.Semaphore(workers)
    counter = {"n": 0}
    total   = len(rows)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--blink-settings=imagesEnabled=false",  # skip images = faster
            ],
        )
        ctx = await browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )

        # fire off all domain batches concurrently
        if download_docs:
            os.makedirs(download_dir, exist_ok=True)
            log.info(f"  document download ON  →  folder: {download_dir}/")

        tasks = [
            run_domain(domain, g, DOMAINS.get(domain, FALLBACK), results, sem, ctx, counter, total, download_docs, download_dir)
            for domain, g in groups.items()
        ]
        await asyncio.gather(*tasks)
        await browser.close()

    # save results
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    log.info(f"saved {len(results)} records → {output_file}")

    # also save a CSV for quick viewing in Excel
    csv_out = output_file.replace(".json", ".csv")
    keys = ["id", "url", "domain", "row_state", "status", "title",
            "contracting_authority", "deadline", "publication_date",
            "tender_type", "reference_number", "scrape_time_ms", "error_message"]
    with open(csv_out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)
    log.info(f"saved csv → {csv_out}")

    # print summary
    total_r   = len(results)
    success   = sum(1 for r in results if r["status"] == "success")
    errors    = sum(1 for r in results if r["status"] == "error")
    timeouts  = sum(1 for r in results if r["status"] == "timeout")
    invalid   = sum(1 for r in results if r["status"] == "invalid")
    avg_ms    = sum(r["scrape_time_ms"] for r in results) / total_r if total_r else 0

    print("\n" + "=" * 55)
    print("  RESULTS")
    print("=" * 55)
    print(f"  total       {total_r}")
    print(f"  success     {success}  ({100*success/total_r:.1f}%)")
    print(f"  errors      {errors}  ({100*errors/total_r:.1f}%)")
    print(f"  timeouts    {timeouts}  ({100*timeouts/total_r:.1f}%)")
    print(f"  invalid     {invalid}  ({100*invalid/total_r:.1f}%)")
    print(f"  avg time    {avg_ms:.0f}ms per url")
    print("=" * 55)

    # per-domain breakdown
    domain_stats = {}
    for r in results:
        d = r["domain"]
        domain_stats.setdefault(d, {"total": 0, "success": 0})
        domain_stats[d]["total"] += 1
        if r["status"] == "success":
            domain_stats[d]["success"] += 1

    # also print how many docs were downloaded total
    total_docs = sum(len(r.get("downloaded_docs", [])) for r in results)
    if total_docs:
        print(f"\n  documents downloaded: {total_docs} files  →  {download_dir}/")

    print("\n  per domain:")
    for d, s in sorted(domain_stats.items(), key=lambda x: -x[1]["total"]):
        rate = 100 * s["success"] / s["total"] if s["total"] else 0
        print(f"    {d:45s}  {s['success']:>5}/{s['total']:<5}  ({rate:.0f}%)")
    print()


# -------------------------------------------------------------------
# CLI - run from terminal
# -------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="German procurement portal scraper")
    p.add_argument("--input",  "-i", default="publications_b.csv", help="input CSV")
    p.add_argument("--output", "-o", default="results.json",       help="output JSON")
    p.add_argument("--workers","-w", type=int, default=8,          help="parallel tabs (default 8)")
    p.add_argument("--limit",  "-n", type=int, default=0,          help="only first N urls (0=all)")
    p.add_argument("--skip-completed", action="store_true",        help="skip rows where state=COMPLETED")
    p.add_argument("--download-docs",  action="store_true",        help="download any PDF/ZIP/DOC files found on each page")
    p.add_argument("--download-dir",   default="downloads",        help="folder to save downloaded docs (default: downloads/)")
    args = p.parse_args()

    if not os.path.exists(args.input):
        print(f"file not found: {args.input}")
        return

    asyncio.run(run(args.input, args.output, args.workers, args.skip_completed, args.limit, args.download_docs, args.download_dir))


if __name__ == "__main__":
    main()
