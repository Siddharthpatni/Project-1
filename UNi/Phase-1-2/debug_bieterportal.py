"""
Targeted scraper for bieterportal.noncd.db.de (Deutsche Bahn supplier portal).
Run:  python debug_bieterportal.py
"""
from playwright.sync_api import sync_playwright
import json
import time
from pathlib import Path

URL = "https://bieterportal.noncd.db.de/evergabe.bieter/api/supplier/external/deeplink/subproject/f4fca233-59a1-4c2b-b040-3fd418252b27"
OUTPUT_DIR = Path("downloads/bieterportal.noncd.db.de/manual")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def scrape(url: str, output_dir: str) -> dict:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    downloaded_files = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=400)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()

        print(f"[*] Navigating to {url}")
        page.goto(url, timeout=60000)

        # Wait for Angular to render the label/value rows
        page.wait_for_selector(".flex-basis-40", timeout=30000)
        time.sleep(2)
        print(f"[*] Page ready: {page.title()}")
        print(f"[*] URL: {page.url}")

        # ── Extract all label → value pairs ───────────────────────────
        metadata = {}
        for row in page.query_selector_all(".flex-row.margin-bottom-5, .flex-row"):
            label_el = row.query_selector(".flex-basis-40")
            value_el = row.query_selector(".flex-basis-60")
            if not label_el or not value_el:
                continue
            label = label_el.inner_text().strip()
            value = value_el.inner_text().strip()
            if label and value:
                metadata[label] = value

        print(f"[*] Metadata extracted: {list(metadata.keys())}")

        tender = {
            "title":       metadata.get("Titel") or metadata.get("Projekttitel") or page.title(),
            "authority":   metadata.get("Auftraggeber", ""),
            "reference":   metadata.get("Vergabenummer") or metadata.get("Kennnummer", ""),
            "deadline":    metadata.get("Einreichungsfrist", ""),
            "published":   metadata.get("Bekanntmachung", ""),
            "description": metadata.get("Verfahrensbeschreibung", ""),
            "url":         page.url,
            "raw":         metadata,
        }
        print(f"[*] Deadline: {tender['deadline']}")
        print(f"[*] Authority: {tender['authority']}")

        # ── Click "Alle herunterladen" and capture the ZIP download ───
        print("[*] Looking for 'Alle herunterladen' button...")
        dl_btn = page.wait_for_selector(
            "button:has-text('Alle herunterladen')", timeout=15000
        )
        print("[*] Found — clicking with expect_download...")
        with page.expect_download(timeout=60000) as dl_info:
            dl_btn.click()

        download = dl_info.value
        dest = output_path / download.suggested_filename
        download.save_as(str(dest))
        downloaded_files.append(str(dest))
        print(f"[+] Downloaded: {dest.name}  ({dest.stat().st_size // 1024} KB)")

        # ── Save metadata ──────────────────────────────────────────────
        result = {"tenders": [tender], "downloaded_files": downloaded_files}
        with open(output_path / "tenders.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"[*] tenders.json saved")

        input("\n[*] Done — press ENTER to close browser.")
        browser.close()

    return result


if __name__ == "__main__":
    r = scrape(URL, str(OUTPUT_DIR))
    print(f"\nResult: {len(r['tenders'])} tender(s), {len(r['downloaded_files'])} file(s)")
