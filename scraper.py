"""
Vergabepilot.AI - Phase 1: Manual Procurement Tender Scraper
=============================================================
A Playwright + XPath based scraper for German public procurement portals.
Designed for the hackathon: maximize scraped websites from ~7,500 URLs.

Supported Domains:
  - evergabe-online.de
  - dtvp.de
  - sachsen-vergabe.de
  - evergabe.de
  - vergabeportal-bw.de
  - (extensible to new domains via domain_configs)

Usage:
  python scraper.py --input urls.csv --output results.json --workers 4
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
        logging.FileHandler("scraper.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("VergabepilotScraper")


# ─── Data Model ──────────────────────────────────────────────────────────────
@dataclass
class TenderRecord:
    """Structured output for a single procurement tender."""
    url: str
    domain: str
    status: str = "pending"  # success | error | timeout | invalid
    title: Optional[str] = None
    description: Optional[str] = None
    contracting_authority: Optional[str] = None  # Auftraggeber
    publication_date: Optional[str] = None       # Veröffentlichungsdatum
    deadline: Optional[str] = None               # Angebotsfrist / Teilnahmefrist
    tender_type: Optional[str] = None            # Verfahrensart
    cpv_codes: Optional[str] = None              # CPV-Codes
    location: Optional[str] = None               # Erfüllungsort
    reference_number: Optional[str] = None       # Vergabenummer / Aktenzeichen
    contact_info: Optional[str] = None
    extra_fields: dict = field(default_factory=dict)
    scraped_at: str = ""
    error_message: Optional[str] = None
    scrape_time_ms: int = 0


# ─── Domain-Specific XPath Configurations ────────────────────────────────────
# Each config defines XPath selectors for extracting fields from a specific domain.
# Adjust these selectors after inspecting the target sites.

DOMAIN_CONFIGS = {
    "www.evergabe-online.de": {
        "name": "eVergabe Online",
        "wait_selector": "//div[contains(@class,'tender') or contains(@class,'detail') or contains(@class,'content')]",
        "selectors": {
            "title": [
                "//h1[contains(@class,'title') or contains(@class,'heading')]",
                "//h1",
                "//div[contains(@class,'tender-title')]",
                "//*[contains(@class,'publication-title')]",
            ],
            "contracting_authority": [
                "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
                "//*[contains(text(),'Vergabestelle')]/following-sibling::*[1]",
                "//td[contains(text(),'Auftraggeber')]/following-sibling::td[1]",
                "//*[contains(@class,'authority') or contains(@class,'client')]",
            ],
            "description": [
                "//*[contains(text(),'Beschreibung')]/following-sibling::*[1]",
                "//*[contains(text(),'Leistung')]/following-sibling::*[1]",
                "//*[contains(@class,'description')]",
            ],
            "deadline": [
                "//*[contains(text(),'Angebotsfrist') or contains(text(),'Teilnahmefrist')]/following-sibling::*[1]",
                "//*[contains(text(),'Frist')]/following-sibling::*[1]",
                "//td[contains(text(),'Frist')]/following-sibling::td[1]",
            ],
            "publication_date": [
                "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
                "//*[contains(text(),'Bekanntmachung')]/following-sibling::*[1]",
                "//td[contains(text(),'Datum')]/following-sibling::td[1]",
            ],
            "tender_type": [
                "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
                "//*[contains(text(),'Vergabeart')]/following-sibling::*[1]",
            ],
            "reference_number": [
                "//*[contains(text(),'Vergabenummer') or contains(text(),'Aktenzeichen')]/following-sibling::*[1]",
                "//*[contains(text(),'Referenz')]/following-sibling::*[1]",
            ],
            "cpv_codes": [
                "//*[contains(text(),'CPV')]/following-sibling::*[1]",
            ],
            "location": [
                "//*[contains(text(),'Erfüllungsort') or contains(text(),'Ort der Leistung')]/following-sibling::*[1]",
            ],
            "contact_info": [
                "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
                "//*[contains(@class,'contact')]",
            ],
        },
    },

    "www.dtvp.de": {
        "name": "DTVP",
        "wait_selector": "//div[contains(@class,'notice') or contains(@class,'detail') or contains(@class,'content')]",
        "selectors": {
            "title": [
                "//h1",
                "//*[contains(@class,'notice-title')]",
                "//div[contains(@class,'headline')]//h1",
            ],
            "contracting_authority": [
                "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
                "//*[contains(text(),'Vergabestelle')]/following-sibling::*[1]",
                "//dt[contains(text(),'Auftraggeber')]/following-sibling::dd[1]",
            ],
            "description": [
                "//*[contains(text(),'Beschreibung')]/following-sibling::*[1]",
                "//*[contains(text(),'Gegenstand')]/following-sibling::*[1]",
            ],
            "deadline": [
                "//*[contains(text(),'Frist')]/following-sibling::*[1]",
                "//dt[contains(text(),'Frist')]/following-sibling::dd[1]",
            ],
            "publication_date": [
                "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
                "//*[contains(text(),'Datum')]/following-sibling::*[1]",
            ],
            "tender_type": [
                "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
            ],
            "reference_number": [
                "//*[contains(text(),'Vergabenummer')]/following-sibling::*[1]",
                "//*[contains(text(),'Referenz')]/following-sibling::*[1]",
            ],
            "cpv_codes": [
                "//*[contains(text(),'CPV')]/following-sibling::*[1]",
            ],
            "location": [
                "//*[contains(text(),'Erfüllungsort')]/following-sibling::*[1]",
            ],
            "contact_info": [
                "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
            ],
        },
    },

    "www.sachsen-vergabe.de": {
        "name": "Sachsen Vergabe",
        "wait_selector": "//div[contains(@class,'detail') or contains(@class,'content') or contains(@class,'publication')]",
        "selectors": {
            "title": [
                "//h1",
                "//*[contains(@class,'title')]",
            ],
            "contracting_authority": [
                "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
                "//td[contains(text(),'Auftraggeber')]/following-sibling::td[1]",
            ],
            "description": [
                "//*[contains(text(),'Beschreibung')]/following-sibling::*[1]",
                "//*[contains(text(),'Leistung')]/following-sibling::*[1]",
            ],
            "deadline": [
                "//*[contains(text(),'Frist')]/following-sibling::*[1]",
            ],
            "publication_date": [
                "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
            ],
            "tender_type": [
                "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
            ],
            "reference_number": [
                "//*[contains(text(),'Vergabenummer')]/following-sibling::*[1]",
            ],
            "cpv_codes": [
                "//*[contains(text(),'CPV')]/following-sibling::*[1]",
            ],
            "location": [
                "//*[contains(text(),'Erfüllungsort')]/following-sibling::*[1]",
            ],
            "contact_info": [
                "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
            ],
        },
    },

    "www.evergabe.de": {
        "name": "eVergabe.de",
        "wait_selector": "//div[contains(@class,'content') or contains(@class,'detail') or contains(@class,'tender')]",
        "selectors": {
            "title": [
                "//h1",
                "//*[contains(@class,'tender-title') or contains(@class,'title')]",
            ],
            "contracting_authority": [
                "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
                "//*[contains(text(),'Vergabestelle')]/following-sibling::*[1]",
            ],
            "description": [
                "//*[contains(text(),'Beschreibung')]/following-sibling::*[1]",
            ],
            "deadline": [
                "//*[contains(text(),'Frist')]/following-sibling::*[1]",
                "//*[contains(text(),'Angebotsfrist')]/following-sibling::*[1]",
            ],
            "publication_date": [
                "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
            ],
            "tender_type": [
                "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
            ],
            "reference_number": [
                "//*[contains(text(),'Vergabenummer')]/following-sibling::*[1]",
            ],
            "cpv_codes": [
                "//*[contains(text(),'CPV')]/following-sibling::*[1]",
            ],
            "location": [
                "//*[contains(text(),'Erfüllungsort')]/following-sibling::*[1]",
            ],
            "contact_info": [
                "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
            ],
        },
    },

    "vergabeportal-bw.de": {
        "name": "Vergabeportal BW",
        "wait_selector": "//div[contains(@class,'content') or contains(@class,'detail') or contains(@class,'notice')]",
        "selectors": {
            "title": [
                "//h1",
                "//*[contains(@class,'title')]",
            ],
            "contracting_authority": [
                "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
            ],
            "description": [
                "//*[contains(text(),'Beschreibung')]/following-sibling::*[1]",
            ],
            "deadline": [
                "//*[contains(text(),'Frist')]/following-sibling::*[1]",
            ],
            "publication_date": [
                "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
            ],
            "tender_type": [
                "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
            ],
            "reference_number": [
                "//*[contains(text(),'Vergabenummer')]/following-sibling::*[1]",
            ],
            "cpv_codes": [
                "//*[contains(text(),'CPV')]/following-sibling::*[1]",
            ],
            "location": [
                "//*[contains(text(),'Erfüllungsort')]/following-sibling::*[1]",
            ],
            "contact_info": [
                "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
            ],
        },
    },
}

# Fallback config for unknown domains
FALLBACK_CONFIG = {
    "name": "Generic",
    "wait_selector": "//body",
    "selectors": {
        "title": ["//h1", "//title"],
        "contracting_authority": [
            "//*[contains(text(),'Auftraggeber')]/following-sibling::*[1]",
            "//*[contains(text(),'Vergabestelle')]/following-sibling::*[1]",
        ],
        "description": [
            "//*[contains(text(),'Beschreibung')]/following-sibling::*[1]",
        ],
        "deadline": [
            "//*[contains(text(),'Frist')]/following-sibling::*[1]",
        ],
        "publication_date": [
            "//*[contains(text(),'Veröffentlich')]/following-sibling::*[1]",
        ],
        "tender_type": [
            "//*[contains(text(),'Verfahrensart')]/following-sibling::*[1]",
        ],
        "reference_number": [
            "//*[contains(text(),'Vergabenummer')]/following-sibling::*[1]",
        ],
        "cpv_codes": [
            "//*[contains(text(),'CPV')]/following-sibling::*[1]",
        ],
        "location": [
            "//*[contains(text(),'Erfüllungsort')]/following-sibling::*[1]",
        ],
        "contact_info": [
            "//*[contains(text(),'Kontakt')]/following-sibling::*[1]",
        ],
    },
}


# ─── Helper Functions ────────────────────────────────────────────────────────

def get_domain(url: str) -> str:
    """Extract domain from URL."""
    parsed = urlparse(url)
    return parsed.netloc.lower()


def get_config(domain: str) -> dict:
    """Get scraping config for a domain, fall back to generic."""
    # Try exact match first
    if domain in DOMAIN_CONFIGS:
        return DOMAIN_CONFIGS[domain]
    # Try partial match (e.g., subdomain variations)
    for key, config in DOMAIN_CONFIGS.items():
        if key in domain or domain in key:
            return config
    return FALLBACK_CONFIG


def load_urls(filepath: str) -> list[dict]:
    """Load URLs from CSV. Expects at minimum a 'url' column."""
    urls = []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            urls.append(row)
    logger.info(f"Loaded {len(urls)} URLs from {filepath}")
    return urls


def group_urls_by_domain(url_rows: list[dict]) -> dict[str, list[dict]]:
    """Group URLs by domain for efficient batch processing."""
    groups = {}
    for row in url_rows:
        domain = get_domain(row["url"])
        groups.setdefault(domain, []).append(row)
    for domain, rows in groups.items():
        logger.info(f"  {domain}: {len(rows)} URLs")
    return groups


# ─── Core Scraper ────────────────────────────────────────────────────────────

async def extract_field(page: Page, xpath_list: list[str]) -> Optional[str]:
    """Try multiple XPath selectors, return first match's text content."""
    for xpath in xpath_list:
        try:
            elements = await page.locator(f"xpath={xpath}").all()
            if elements:
                text = await elements[0].inner_text()
                text = text.strip()
                if text:
                    return text
        except Exception:
            continue
    return None


async def extract_all_key_value_pairs(page: Page) -> dict:
    """
    Fallback: extract all visible label-value pairs from the page.
    Looks for common patterns: <dt>/<dd>, <th>/<td>, label/value divs.
    """
    extra = {}
    try:
        # Pattern 1: Definition lists (dt/dd)
        dts = await page.locator("xpath=//dt").all()
        for dt in dts:
            try:
                label = (await dt.inner_text()).strip()
                dd = await dt.evaluate("el => el.nextElementSibling?.textContent?.trim()")
                if label and dd:
                    extra[label] = dd
            except Exception:
                continue

        # Pattern 2: Table rows (th/td or td/td)
        rows = await page.locator("xpath=//tr").all()
        for row in rows:
            try:
                cells = await row.locator("td, th").all()
                if len(cells) >= 2:
                    label = (await cells[0].inner_text()).strip()
                    value = (await cells[1].inner_text()).strip()
                    if label and value and len(label) < 100:
                        extra[label] = value
            except Exception:
                continue

    except Exception:
        pass
    return extra


async def handle_cookie_consent(page: Page):
    """Dismiss cookie banners if present."""
    consent_selectors = [
        "xpath=//button[contains(text(),'Akzeptieren')]",
        "xpath=//button[contains(text(),'Alle akzeptieren')]",
        "xpath=//button[contains(text(),'Accept')]",
        "xpath=//button[contains(text(),'Zustimmen')]",
        "xpath=//a[contains(text(),'Akzeptieren')]",
        "xpath=//button[contains(@class,'accept') or contains(@class,'consent') or contains(@class,'agree')]",
        "xpath=//button[@id='accept' or @id='consent']",
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


async def scrape_single_url(page: Page, url: str, config: dict) -> TenderRecord:
    """Scrape a single tender URL using the given domain config."""
    domain = get_domain(url)
    record = TenderRecord(url=url, domain=domain)
    start = time.time()

    try:
        # Navigate with timeout
        response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)

        # Check HTTP status
        if response and response.status >= 400:
            record.status = "invalid"
            record.error_message = f"HTTP {response.status}"
            return record

        # Wait briefly for dynamic content
        await page.wait_for_timeout(1500)

        # Handle cookie consent
        await handle_cookie_consent(page)

        # Try to wait for content selector
        try:
            await page.wait_for_selector(
                f"xpath={config['wait_selector']}", timeout=5000
            )
        except PlaywrightTimeout:
            pass  # Continue anyway, page might still have content

        # Check for common "expired/removed" indicators
        body_text = await page.inner_text("body")
        expired_indicators = [
            "nicht mehr verfügbar",
            "nicht gefunden",
            "abgelaufen",
            "Seite existiert nicht",
            "404",
            "Vergabe wurde aufgehoben",
            "Bekanntmachung wurde gelöscht",
        ]
        for indicator in expired_indicators:
            if indicator.lower() in body_text.lower():
                record.status = "invalid"
                record.error_message = f"Tender expired/removed: '{indicator}'"
                return record

        # Extract structured fields
        selectors = config.get("selectors", {})
        for field_name, xpath_list in selectors.items():
            value = await extract_field(page, xpath_list)
            if value and hasattr(record, field_name):
                setattr(record, field_name, value)

        # Fallback: grab all key-value pairs
        record.extra_fields = await extract_all_key_value_pairs(page)

        # Determine success
        if record.title or record.contracting_authority or record.extra_fields:
            record.status = "success"
        else:
            record.status = "error"
            record.error_message = "No data extracted"

    except PlaywrightTimeout:
        record.status = "timeout"
        record.error_message = "Page load timed out (15s)"
    except Exception as e:
        record.status = "error"
        record.error_message = str(e)[:200]

    record.scrape_time_ms = int((time.time() - start) * 1000)
    record.scraped_at = datetime.now().isoformat()
    return record


# ─── Batch Processing ────────────────────────────────────────────────────────

async def scrape_domain_batch(
    domain: str,
    url_rows: list[dict],
    config: dict,
    results: list,
    semaphore: asyncio.Semaphore,
    browser_context,
):
    """Scrape all URLs for a given domain using shared browser context."""
    logger.info(f"Starting batch for {domain} ({len(url_rows)} URLs)")
    page = await browser_context.new_page()

    for i, row in enumerate(url_rows):
        async with semaphore:
            url = row["url"]
            record = await scrape_single_url(page, url, config)

            # Attach metadata from CSV if available
            for key in ["id", "trigger_id", "procedure_id"]:
                if key in row and row[key]:
                    record.extra_fields[key] = row[key]

            results.append(record)

            status_icon = "✓" if record.status == "success" else "✗"
            logger.info(
                f"  [{status_icon}] [{i+1}/{len(url_rows)}] {domain} | "
                f"{record.status} | {record.scrape_time_ms}ms | {url[:80]}..."
            )

    await page.close()
    logger.info(f"Completed batch for {domain}")


async def run_scraper(input_file: str, output_file: str, max_concurrent: int = 4):
    """Main scraper orchestration."""
    # Load and group URLs
    url_rows = load_urls(input_file)
    domain_groups = group_urls_by_domain(url_rows)

    results: list[TenderRecord] = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-images",  # Speed up by skipping images
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

        # Process each domain group
        tasks = []
        for domain, rows in domain_groups.items():
            config = get_config(domain)
            tasks.append(
                scrape_domain_batch(domain, rows, config, results, semaphore, context)
            )

        await asyncio.gather(*tasks)
        await browser.close()

    # Write results
    save_results(results, output_file)
    print_summary(results)


def save_results(results: list[TenderRecord], output_file: str):
    """Save results to JSON (and a parallel CSV for quick review)."""
    # JSON output
    data = [asdict(r) for r in results]
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(results)} records to {output_file}")

    # CSV output for quick review
    csv_file = output_file.replace(".json", ".csv")
    if results:
        fieldnames = [
            "url", "domain", "status", "title", "contracting_authority",
            "deadline", "publication_date", "tender_type", "reference_number",
            "scrape_time_ms", "error_message",
        ]
        with open(csv_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                writer.writerow(asdict(r))
        logger.info(f"Saved CSV summary to {csv_file}")


def print_summary(results: list[TenderRecord]):
    """Print scraping statistics."""
    total = len(results)
    success = sum(1 for r in results if r.status == "success")
    errors = sum(1 for r in results if r.status == "error")
    timeouts = sum(1 for r in results if r.status == "timeout")
    invalid = sum(1 for r in results if r.status == "invalid")
    avg_time = sum(r.scrape_time_ms for r in results) / total if total else 0

    print("\n" + "=" * 60)
    print("  SCRAPING SUMMARY")
    print("=" * 60)
    print(f"  Total URLs:      {total}")
    print(f"  ✓ Success:       {success} ({100*success/total:.1f}%)")
    print(f"  ✗ Errors:        {errors} ({100*errors/total:.1f}%)")
    print(f"  ⏱ Timeouts:      {timeouts} ({100*timeouts/total:.1f}%)")
    print(f"  ⊘ Invalid/Expired: {invalid} ({100*invalid/total:.1f}%)")
    print(f"  Avg scrape time: {avg_time:.0f}ms")
    print("=" * 60)

    # Per-domain breakdown
    domains = {}
    for r in results:
        domains.setdefault(r.domain, {"total": 0, "success": 0})
        domains[r.domain]["total"] += 1
        if r.status == "success":
            domains[r.domain]["success"] += 1

    print("\n  Per-Domain Breakdown:")
    for domain, stats in sorted(domains.items(), key=lambda x: -x[1]["total"]):
        rate = 100 * stats["success"] / stats["total"] if stats["total"] else 0
        print(f"    {domain:40s} {stats['success']:>5}/{stats['total']:<5} ({rate:.0f}%)")
    print()


# ─── CLI Entry Point ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Vergabepilot.AI - Manual Procurement Tender Scraper"
    )
    parser.add_argument(
        "--input", "-i", required=True,
        help="Path to CSV file with URLs (must have 'url' column)",
    )
    parser.add_argument(
        "--output", "-o", default="results.json",
        help="Output JSON file path (default: results.json)",
    )
    parser.add_argument(
        "--workers", "-w", type=int, default=4,
        help="Max concurrent scraping tasks (default: 4)",
    )
    args = parser.parse_args()

    if not os.path.exists(args.input):
        logger.error(f"Input file not found: {args.input}")
        return

    asyncio.run(run_scraper(args.input, args.output, args.workers))


if __name__ == "__main__":
    main()
