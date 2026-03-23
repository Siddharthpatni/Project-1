"""
Vergabepilot.AI — Phase 1: Enhanced Scraper for publications_b.csv
===================================================================
Playwright + XPath scraper covering all major German procurement portals
found in publications_b.csv (~7,500 URLs, 20+ domains).

Usage:
  python scraper_b.py --input publications_b.csv --output results_b.json --workers 8
"""

import asyncio
import csv
import json
import logging
import time
import argparse
import os
from datetime import datetime
from urllib.parse import urlparse
from dataclasses import dataclass, asdict, field
from typing import Optional
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

# ─── Logging Setup ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scraper_b.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("VergabepilotScraper_B")


# ─── Data Model ──────────────────────────────────────────────────────────────
@dataclass
class TenderRecord:
    """Structured output for a single procurement tender."""
    url: str
    domain: str
    row_id: str = ""
    row_state: str = ""          # original state from CSV
    status: str = "pending"      # success | error | timeout | invalid | skipped
    title: Optional[str] = None
    description: Optional[str] = None
    contracting_authority: Optional[str] = None
    publication_date: Optional[str] = None
    deadline: Optional[str] = None
    tender_type: Optional[str] = None
    cpv_codes: Optional[str] = None
    location: Optional[str] = None
    reference_number: Optional[str] = None
    contact_info: Optional[str] = None
    extra_fields: dict = field(default_factory=dict)
    scraped_at: str = ""
    error_message: Optional[str] = None
    scrape_time_ms: int = 0


# ─── Shared XPath selector sets for common German procurement patterns ────────
COMMON_TITLE_XPATHS = [
    "//h1",
    "//*[contains(@class,'title') and (self::h1 or self::h2 or self::div or self::span)]",
    "//title",
]

COMMON_AUTHORITY_XPATHS = [
    "//dt[contains(.,'Auftraggeber')]/following-sibling::dd[1]",
    "//th[contains(.,'Auftraggeber')]/following-sibling::td[1]",
    "//td[contains(.,'Auftraggeber')]/following-sibling::td[1]",
    "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
    "//*[contains(text(),'Vergabestelle')]/following-sibling::*[1]",
    "//*[contains(@class,'authority') or contains(@class,'client-name')]",
]

COMMON_DEADLINE_XPATHS = [
    "//dt[contains(.,'Angebotsfrist') or contains(.,'Teilnahmefrist') or contains(.,'Frist')]/following-sibling::dd[1]",
    "//th[contains(.,'Frist')]/following-sibling::td[1]",
    "//td[contains(.,'Frist')]/following-sibling::td[1]",
    "//*[contains(text(),'Angebotsfrist') or contains(text(),'Teilnahmefrist')]/following-sibling::*[1]",
    "//*[contains(text(),'Frist')]/following-sibling::*[1]",
]

COMMON_DATE_XPATHS = [
    "//dt[contains(.,'Veröffentlich')]/following-sibling::dd[1]",
    "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
    "//*[contains(text(),'Bekanntmachung')]/following-sibling::*[1]",
]

COMMON_TYPE_XPATHS = [
    "//dt[contains(.,'Verfahrensart') or contains(.,'Vergabeart')]/following-sibling::dd[1]",
    "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
]

COMMON_CPV_XPATHS = [
    "//*[contains(text(),'CPV')]/following-sibling::*[1]",
    "//dt[contains(.,'CPV')]/following-sibling::dd[1]",
]

COMMON_LOCATION_XPATHS = [
    "//*[contains(text(),'Erfüllungsort') or contains(text(),'Ort der Leistung')]/following-sibling::*[1]",
]

COMMON_REF_XPATHS = [
    "//dt[contains(.,'Vergabenummer') or contains(.,'Aktenzeichen') or contains(.,'Referenz')]/following-sibling::dd[1]",
    "//*[contains(text(),'Vergabenummer') or contains(text(),'Aktenzeichen')]/following-sibling::*[1]",
]

COMMON_DESC_XPATHS = [
    "//*[contains(text(),'Beschreibung') or contains(text(),'Leistung')]/following-sibling::*[1]",
    "//*[contains(@class,'description') or contains(@class,'leistung')]",
]

COMMON_CONTACT_XPATHS = [
    "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
    "//*[contains(@class,'contact')]",
]

def _selectors(title=None, authority=None, description=None, deadline=None,
               pub_date=None, t_type=None, cpv=None, location=None,
               ref=None, contact=None):
    return {
        "title": (title or []) + COMMON_TITLE_XPATHS,
        "contracting_authority": (authority or []) + COMMON_AUTHORITY_XPATHS,
        "description": (description or []) + COMMON_DESC_XPATHS,
        "deadline": (deadline or []) + COMMON_DEADLINE_XPATHS,
        "publication_date": (pub_date or []) + COMMON_DATE_XPATHS,
        "tender_type": (t_type or []) + COMMON_TYPE_XPATHS,
        "cpv_codes": (cpv or []) + COMMON_CPV_XPATHS,
        "location": (location or []) + COMMON_LOCATION_XPATHS,
        "reference_number": (ref or []) + COMMON_REF_XPATHS,
        "contact_info": (contact or []) + COMMON_CONTACT_XPATHS,
    }


# ─── Domain Configurations ───────────────────────────────────────────────────
DOMAIN_CONFIGS = {
    # ── evergabe.de ──────────────────────────────────────────────────────────
    "www.evergabe.de": {
        "name": "eVergabe.de",
        "wait_selector": "//h1 | //div[contains(@class,'content')]",
        "selectors": _selectors(
            title=["//h1[contains(@class,'title')]", "//h1"],
            authority=[
                "//*[contains(@class,'vergabestelle') or contains(@class,'authority')]",
                "//span[contains(text(),'Auftraggeber')]/following-sibling::span[1]",
            ],
        ),
    },

    # ── subreport.de ─────────────────────────────────────────────────────────
    "www.subreport.de": {
        "name": "Subreport",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'bekanntmachung')]",
        "selectors": _selectors(
            title=[
                "//h1[contains(@class,'bekanntmachung-titel') or contains(@class,'title')]",
                "//h1",
                "//div[contains(@class,'bekanntmachungstitel')]",
            ],
            authority=[
                "//span[contains(@id,'lblVergabestelle') or contains(@id,'lblAuftraggeber')]",
                "//td[contains(text(),'Vergabestelle') or contains(text(),'Auftraggeber')]/following-sibling::td[1]",
            ],
            deadline=[
                "//span[contains(@id,'lblAngebotsfrist') or contains(@id,'lblTeilnahmefrist')]",
                "//td[contains(text(),'Angebotsfrist') or contains(text(),'Frist')]/following-sibling::td[1]",
            ],
        ),
    },

    # ── vergabemarktplatz.brandenburg.de ─────────────────────────────────────
    "vergabemarktplatz.brandenburg.de": {
        "name": "Vergabemarktplatz Brandenburg",
        "wait_selector": "//div[contains(@class,'notice') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'notice-title')]"],
            authority=[
                "//*[contains(@class,'organisation-name') or contains(@class,'authority')]",
            ],
            deadline=["//*[contains(@class,'deadline') or contains(@class,'frist')]"],
        ),
    },

    # ── vergabe.niedersachsen.de ──────────────────────────────────────────────
    "vergabe.niedersachsen.de": {
        "name": "Vergabe Niedersachsen",
        "wait_selector": "//div[contains(@class,'notice') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'notice-title')]"],
        ),
    },

    # ── bieterzugang.deutsche-evergabe.de ────────────────────────────────────
    "bieterzugang.deutsche-evergabe.de": {
        "name": "Deutsche eVergabe",
        "wait_selector": "//div | //h1",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'title')]"],
        ),
    },

    # ── www.evergabe.nrw.de ───────────────────────────────────────────────────
    "www.evergabe.nrw.de": {
        "name": "eVergabe NRW",
        "wait_selector": "//div[contains(@class,'notice') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'notice-title')]"],
        ),
    },

    # ── www.vergabe-westfalen.de ──────────────────────────────────────────────
    "www.vergabe-westfalen.de": {
        "name": "Vergabe Westfalen",
        "wait_selector": "//div[contains(@class,'notice') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'notice-title')]"],
        ),
    },

    # ── www.deutsches-ausschreibungsblatt.de ─────────────────────────────────
    "www.deutsches-ausschreibungsblatt.de": {
        "name": "Deutsches Ausschreibungsblatt",
        "wait_selector": "//div[contains(@class,'content') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//h2[contains(@class,'title')]"],
            authority=[
                "//td[contains(text(),'Auftraggeber')]/following-sibling::td[1]",
                "//span[contains(@class,'auftraggeber')]",
            ],
        ),
    },

    # ── www.had.de ───────────────────────────────────────────────────────────
    "www.had.de": {
        "name": "HAD",
        "wait_selector": "//div[contains(@class,'content') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//td[contains(@class,'title')]"],
            authority=["//td[contains(text(),'Auftraggeber')]/following-sibling::td[1]"],
            deadline=["//td[contains(text(),'Frist') or contains(text(),'Abgabetermin')]/following-sibling::td[1]"],
        ),
    },

    # ── www.vergabe.metropoleruhr.de ──────────────────────────────────────────
    "www.vergabe.metropoleruhr.de": {
        "name": "Vergabe Metropole Ruhr",
        "wait_selector": "//div[contains(@class,'notice') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'notice-title')]"],
        ),
    },

    # ── fbhh-evergabe.web.hamburg.de ─────────────────────────────────────────
    "fbhh-evergabe.web.hamburg.de": {
        "name": "eVergabe Hamburg",
        "wait_selector": "//div | //h1",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'title')]"],
        ),
    },

    # ── bi-medien.de ─────────────────────────────────────────────────────────
    "bi-medien.de": {
        "name": "BI Medien",
        "wait_selector": "//div[contains(@class,'content') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//h2[contains(@class,'title')]"],
            authority=["//span[contains(@class,'auftraggeber') or contains(@class,'vergabestelle')]"],
        ),
    },

    # ── www.tender24.de ───────────────────────────────────────────────────────
    "www.tender24.de": {
        "name": "Tender24",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'tender')]",
        "selectors": _selectors(
            title=["//h1", "//div[contains(@class,'TenderTitle')]"],
            authority=[
                "//span[@id='lblVergabestelle']",
                "//td[contains(text(),'Vergabestelle')]/following-sibling::td[1]",
            ],
            deadline=["//span[@id='lblAngebotsfrist']"],
        ),
    },

    # ── vergabe.landbw.de ─────────────────────────────────────────────────────
    "vergabe.landbw.de": {
        "name": "Vergabe LandBW",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'tender')]",
        "selectors": _selectors(
            title=["//h1"],
        ),
    },

    # ── www.vergabe24.de ──────────────────────────────────────────────────────
    "www.vergabe24.de": {
        "name": "Vergabe24",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'tender')]",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'title')]"],
            authority=["//span[@id='lblVergabestelle']"],
        ),
    },

    # ── vergabekooperation.berlin ─────────────────────────────────────────────
    "vergabekooperation.berlin": {
        "name": "Vergabekooperation Berlin",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'tender')]",
        "selectors": _selectors(
            title=["//h1"],
        ),
    },

    # ── www.evergabe.bayern.de ────────────────────────────────────────────────
    "www.evergabe.bayern.de": {
        "name": "eVergabe Bayern",
        "wait_selector": "//div | //h1",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'title')]"],
        ),
    },

    # ── vergabeportal-bw.de ───────────────────────────────────────────────────
    "vergabeportal-bw.de": {
        "name": "Vergabeportal BW",
        "wait_selector": "//div[contains(@class,'notice') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'title')]"],
        ),
    },

    # ── vergabe.fraunhofer.de ─────────────────────────────────────────────────
    "vergabe.fraunhofer.de": {
        "name": "Vergabe Fraunhofer",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'tender')]",
        "selectors": _selectors(
            title=["//h1"],
        ),
    },

    # ── www.ausschreibungen.ls.brandenburg.de ─────────────────────────────────
    "www.ausschreibungen.ls.brandenburg.de": {
        "name": "Ausschreibungen LS Brandenburg",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'tender')]",
        "selectors": _selectors(title=["//h1"]),
    },

    # ── landesverwaltung.vergabe.rlp.de ──────────────────────────────────────
    "landesverwaltung.vergabe.rlp.de": {
        "name": "Vergabe RLP",
        "wait_selector": "//div[contains(@class,'notice')]",
        "selectors": _selectors(title=["//h1"]),
    },

    # ── lbb.vergabe.rlp.de ───────────────────────────────────────────────────
    "lbb.vergabe.rlp.de": {
        "name": "LBB Vergabe RLP",
        "wait_selector": "//div[contains(@class,'notice')]",
        "selectors": _selectors(title=["//h1"]),
    },

    # ── vergabe.deges.de ─────────────────────────────────────────────────────
    "vergabe.deges.de": {
        "name": "Vergabe DEGES",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'tender')]",
        "selectors": _selectors(title=["//h1"]),
    },

    # ── vergabe.bwbm.de ───────────────────────────────────────────────────────
    "vergabe.bwbm.de": {
        "name": "Vergabe BWBM",
        "wait_selector": "//div",
        "selectors": _selectors(title=["//h1"]),
    },

    # ── www.evergabe-online.de ────────────────────────────────────────────────
    "www.evergabe-online.de": {
        "name": "eVergabe Online",
        "wait_selector": "//div[contains(@class,'tender') or contains(@class,'detail')]",
        "selectors": _selectors(
            title=["//h1", "//*[contains(@class,'publication-title')]"],
        ),
    },

    # ── www.evergabe.sachsen.de ───────────────────────────────────────────────
    "www.evergabe.sachsen.de": {
        "name": "eVergabe Sachsen",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'tender')]",
        "selectors": _selectors(title=["//h1"]),
    },

    # ── s2c.mercell.com ───────────────────────────────────────────────────────
    "s2c.mercell.com": {
        "name": "Mercell",
        "wait_selector": "//div",
        "selectors": _selectors(title=["//h1", "//*[contains(@class,'title')]"]),
    },
}

# ── Fallback config ───────────────────────────────────────────────────────────
FALLBACK_CONFIG = {
    "name": "Generic",
    "wait_selector": "//body",
    "selectors": _selectors(),
}


# ─── Helper Functions ─────────────────────────────────────────────────────────

def get_domain(url: str) -> str:
    return urlparse(url).netloc.lower()


def get_config(domain: str) -> dict:
    if domain in DOMAIN_CONFIGS:
        return DOMAIN_CONFIGS[domain]
    for key, config in DOMAIN_CONFIGS.items():
        if key in domain or domain in key:
            return config
    return FALLBACK_CONFIG


def load_urls(filepath: str) -> list[dict]:
    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("url", "").strip():
                urls.append(row)
    logger.info(f"Loaded {len(urls)} URLs from {filepath}")
    return urls


def group_urls_by_domain(url_rows: list[dict]) -> dict[str, list[dict]]:
    groups = {}
    for row in url_rows:
        domain = get_domain(row["url"])
        groups.setdefault(domain, []).append(row)
    for domain, rows in sorted(groups.items(), key=lambda x: -len(x[1])):
        logger.info(f"  {domain}: {len(rows)} URLs")
    return groups


# ─── Core Scraper ─────────────────────────────────────────────────────────────

async def extract_field(page: Page, xpath_list: list[str]) -> Optional[str]:
    for xpath in xpath_list:
        try:
            elements = await page.locator(f"xpath={xpath}").all()
            if elements:
                text = (await elements[0].inner_text()).strip()
                if text and len(text) < 2000:
                    return text
        except Exception:
            continue
    return None


async def extract_all_key_value_pairs(page: Page) -> dict:
    extra = {}
    try:
        # Definition lists
        dts = await page.locator("xpath=//dt").all()
        for dt in dts:
            try:
                label = (await dt.inner_text()).strip()
                dd = await dt.evaluate("el => el.nextElementSibling?.textContent?.trim()")
                if label and dd and len(label) < 150:
                    extra[label] = dd
            except Exception:
                continue

        # Table rows
        rows = await page.locator("xpath=//tr").all()
        for row in rows:
            try:
                cells = await row.locator("td, th").all()
                if len(cells) >= 2:
                    label = (await cells[0].inner_text()).strip()
                    value = (await cells[1].inner_text()).strip()
                    if label and value and len(label) < 150:
                        extra[label] = value
            except Exception:
                continue
    except Exception:
        pass
    return extra


async def handle_cookie_consent(page: Page):
    consent_selectors = [
        "xpath=//button[contains(text(),'Akzeptieren')]",
        "xpath=//button[contains(text(),'Alle akzeptieren')]",
        "xpath=//button[contains(text(),'Accept')]",
        "xpath=//button[contains(text(),'Zustimmen')]",
        "xpath=//button[contains(text(),'Ablehnen') or contains(text(),'Nur notwendige')]",
        "xpath=//button[contains(@class,'accept') or contains(@class,'consent') or contains(@class,'agree')]",
        "xpath=//button[@id='accept' or @id='consent' or @id='acceptCookies']",
        "xpath=//a[contains(text(),'Akzeptieren')]",
    ]
    for selector in consent_selectors:
        try:
            btn = page.locator(selector).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await page.wait_for_timeout(500)
                logger.debug("Dismissed cookie banner")
                return
        except Exception:
            continue


async def scrape_single_url(page: Page, row: dict, config: dict) -> TenderRecord:
    url = row["url"]
    domain = get_domain(url)
    record = TenderRecord(
        url=url,
        domain=domain,
        row_id=row.get("id", ""),
        row_state=row.get("state", ""),
    )
    start = time.time()

    try:
        response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)

        if response and response.status >= 400:
            record.status = "invalid"
            record.error_message = f"HTTP {response.status}"
            return record

        await page.wait_for_timeout(1500)
        await handle_cookie_consent(page)

        try:
            await page.wait_for_selector(
                f"xpath={config['wait_selector']}", timeout=5000
            )
        except PlaywrightTimeout:
            pass

        # Check for expired/not-found indicators
        try:
            body_text = await page.inner_text("body")
            expired_indicators = [
                "nicht mehr verfügbar",
                "nicht gefunden",
                "abgelaufen",
                "Seite existiert nicht",
                "Page not found",
                "404",
                "Vergabe wurde aufgehoben",
                "Bekanntmachung wurde gelöscht",
                "kein Ergebnis",
                "Kein Treffer",
            ]
            for indicator in expired_indicators:
                if indicator.lower() in body_text.lower()[:5000]:
                    record.status = "invalid"
                    record.error_message = f"Tender expired/removed: '{indicator}'"
                    return record
        except Exception:
            pass

        # Extract structured fields
        selectors = config.get("selectors", {})
        for field_name, xpath_list in selectors.items():
            value = await extract_field(page, xpath_list)
            if value and hasattr(record, field_name):
                setattr(record, field_name, value)

        # Fallback key-value pairs
        record.extra_fields = await extract_all_key_value_pairs(page)

        if record.title or record.contracting_authority or record.extra_fields:
            record.status = "success"
        else:
            record.status = "error"
            record.error_message = "No data extracted"

    except PlaywrightTimeout:
        record.status = "timeout"
        record.error_message = "Page load timed out (20s)"
    except Exception as e:
        record.status = "error"
        record.error_message = str(e)[:300]

    record.scrape_time_ms = int((time.time() - start) * 1000)
    record.scraped_at = datetime.now().isoformat()
    return record


# ─── Batch Processing ─────────────────────────────────────────────────────────

async def scrape_domain_batch(
    domain: str,
    url_rows: list[dict],
    config: dict,
    results: list,
    semaphore: asyncio.Semaphore,
    browser_context,
    counter: dict,
    total_urls: int,
):
    logger.info(f"Starting batch [{domain}] → {len(url_rows)} URLs")
    page = await browser_context.new_page()

    for i, row in enumerate(url_rows):
        async with semaphore:
            record = await scrape_single_url(page, row, config)
            results.append(record)

            counter["done"] += 1
            pct = 100 * counter["done"] / total_urls
            status_icon = "✓" if record.status == "success" else ("⏱" if record.status == "timeout" else "✗")
            logger.info(
                f"  [{status_icon}] [{counter['done']}/{total_urls} {pct:.1f}%] "
                f"{domain} | {record.status} | {record.scrape_time_ms}ms"
            )

    await page.close()
    logger.info(f"✔ Batch complete: {domain}")


async def run_scraper(input_file: str, output_file: str, max_concurrent: int = 8,
                      skip_completed: bool = False, limit: int = 0):
    """Main orchestration."""
    url_rows = load_urls(input_file)

    # Optionally skip rows already COMPLETED
    if skip_completed:
        before = len(url_rows)
        url_rows = [r for r in url_rows if r.get("state", "") != "COMPLETED"]
        logger.info(f"Skipped {before - len(url_rows)} COMPLETED rows; {len(url_rows)} remaining")

    # Optionally cap number of URLs
    if limit and limit > 0:
        url_rows = url_rows[:limit]
        logger.info(f"Limiting to first {limit} URLs")

    domain_groups = group_urls_by_domain(url_rows)

    results: list[TenderRecord] = []
    semaphore = asyncio.Semaphore(max_concurrent)
    counter = {"done": 0}
    total_urls = len(url_rows)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--blink-settings=imagesEnabled=false",
            ],
        )
        context = await browser.new_context(
            locale="de-DE",
            timezone_id="Europe/Berlin",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
        )

        tasks = []
        for domain, rows in domain_groups.items():
            config = get_config(domain)
            tasks.append(
                scrape_domain_batch(
                    domain, rows, config, results,
                    semaphore, context, counter, total_urls,
                )
            )

        await asyncio.gather(*tasks)
        await browser.close()

    save_results(results, output_file)
    print_summary(results)


# ─── Output ───────────────────────────────────────────────────────────────────

def save_results(results: list[TenderRecord], output_file: str):
    data = [asdict(r) for r in results]
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(results)} records → {output_file}")

    csv_file = output_file.replace(".json", ".csv")
    if results:
        fieldnames = [
            "row_id", "url", "domain", "row_state", "status",
            "title", "contracting_authority", "deadline",
            "publication_date", "tender_type", "reference_number",
            "scrape_time_ms", "error_message",
        ]
        with open(csv_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                writer.writerow(asdict(r))
        logger.info(f"Saved CSV summary → {csv_file}")


def print_summary(results: list[TenderRecord]):
    total = len(results)
    if not total:
        print("No results.")
        return

    success = sum(1 for r in results if r.status == "success")
    errors = sum(1 for r in results if r.status == "error")
    timeouts = sum(1 for r in results if r.status == "timeout")
    invalid = sum(1 for r in results if r.status == "invalid")
    avg_time = sum(r.scrape_time_ms for r in results) / total

    print("\n" + "=" * 60)
    print("  SCRAPING SUMMARY")
    print("=" * 60)
    print(f"  Total URLs:        {total}")
    print(f"  ✓ Success:         {success} ({100*success/total:.1f}%)")
    print(f"  ✗ Errors:          {errors} ({100*errors/total:.1f}%)")
    print(f"  ⏱ Timeouts:        {timeouts} ({100*timeouts/total:.1f}%)")
    print(f"  ⊘ Invalid/Expired: {invalid} ({100*invalid/total:.1f}%)")
    print(f"  Avg scrape time:   {avg_time:.0f}ms")
    print("=" * 60)

    domains: dict = {}
    for r in results:
        domains.setdefault(r.domain, {"total": 0, "success": 0})
        domains[r.domain]["total"] += 1
        if r.status == "success":
            domains[r.domain]["success"] += 1

    print("\n  Per-Domain Breakdown:")
    for domain, stats in sorted(domains.items(), key=lambda x: -x[1]["total"]):
        rate = 100 * stats["success"] / stats["total"] if stats["total"] else 0
        print(f"    {domain:45s} {stats['success']:>5}/{stats['total']:<5} ({rate:.0f}%)")
    print()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Vergabepilot.AI — Phase 1 Scraper for publications_b.csv"
    )
    parser.add_argument("--input", "-i", default="publications_b.csv",
                        help="Input CSV (default: publications_b.csv)")
    parser.add_argument("--output", "-o", default="results_b.json",
                        help="Output JSON (default: results_b.json)")
    parser.add_argument("--workers", "-w", type=int, default=8,
                        help="Concurrent Playwright pages (default: 8)")
    parser.add_argument("--skip-completed", action="store_true",
                        help="Skip rows with state=COMPLETED in input CSV")
    parser.add_argument("--limit", "-n", type=int, default=0,
                        help="Only process first N URLs (0 = all, default: 0)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        logger.error(f"Input file not found: {args.input}")
        return

    asyncio.run(run_scraper(args.input, args.output, args.workers, args.skip_completed, args.limit))


if __name__ == "__main__":
    main()
