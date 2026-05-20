"""
Scraper for evergabe-online.de (e-Vergabe des Bundes)
======================================================
1. Visits tenderdetails.html to extract all structured metadata
2. Visits tenderdocuments.html to download all documents as ZIP
3. Saves tenders.json and tenders.csv

Entry point: scrape(url, output_dir) -> dict
Accepts either tenderdetails or tenderdocuments URL — the tender ID is
extracted from the URL and both pages are visited automatically.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs


BASE = "https://www.evergabe-online.de"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_id(url: str) -> str | None:
    """Pull tender ID from any evergabe URL."""
    qs = parse_qs(urlparse(url).query)
    return (qs.get("id") or [None])[0]


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _after_label(text: str, label: str) -> str | None:
    """Extract the value that follows a label in plain text."""
    pattern = re.escape(label) + r"\s*[:\s]\s*(.{2,200}?)(?=\n|$)"
    m = re.search(pattern, text, re.IGNORECASE)
    return _clean(m.group(1)) if m else None


def _extract_metadata(html: str, url: str) -> dict:
    """
    Parse tender metadata from the tenderdetails page HTML.
    All fields are visible in the static HTML (no JS needed).
    """
    # Strip tags and normalise whitespace to get plain text
    clean = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL)
    clean = re.sub(r"<style[^>]*>.*?</style>", " ", clean, flags=re.DOTALL)
    clean = re.sub(r"<[^>]+>", "\n", clean)
    clean = re.sub(r"&nbsp;", " ", clean)
    clean = re.sub(r"&amp;", "&", clean)
    clean = re.sub(r"&#[0-9]+;", "", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()

    def after(label: str) -> str | None:
        return _after_label(clean, label)

    # Title is the h1/h2 after "Ausschreibungsdetails"
    title = None
    m = re.search(r"Ausschreibungsdetails\s*\n+([^\n]{5,200})", clean)
    if m:
        title = _clean(m.group(1))

    return {
        "title":                 title,
        "description":           after("Beschreibung"),
        "contracting_authority": after("Offizielle Bezeichnung") or after("Vergabestelle"),
        "authority_type":        after("Art des öffentlichen Auftraggebers")
                                 or after("Art des .ffentlichen Auftraggebers"),
        "procedure_type":        after("Verfahrensart"),
        "contract_type":         after("Art des Auftrags"),
        "cpv_code":              after("Hauptklassifizierungscode"),
        "publication_date":      after("Veröffentlichungsdatum") or after("Ver.ffentlichungsdatum"),
        "submission_deadline":   after("Abgabefrist Angebot") or after("Einreichungsfrist"),
        "reference":             after("Interne Kennung") or after("Geschäftszeichen") or after("Gesch.ftszeichen"),
        "procedure_id":          after("Kennung des Verfahrens"),
        "location":              after("Erfüllungsort") or after("Erf.llungsort"),
        "start_date":            after("Datum des Beginns"),
        "end_date":              after("Enddatum der Laufzeit"),
        "legal_basis":           after("Rechtsgrundlage"),
        "url":                   url,
    }


def _save_csv(tenders: list[dict], path: Path):
    if not tenders:
        return
    fields = list(tenders[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(tenders)


# ── Main scrape function ───────────────────────────────────────────────────────

def scrape(url: str, output_dir: str) -> dict:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    tender_id = _extract_id(url)
    details_url   = f"{BASE}/tenderdetails.html?id={tender_id}"   if tender_id else url
    documents_url = f"{BASE}/tenderdocuments.html?id={tender_id}" if tender_id else url

    downloaded_files: list[str] = []
    tenders: list[dict] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()

        # ── Step 1: Load details page and extract metadata ─────────────
        print(f"Loading details page: {details_url}")
        try:
            page.goto(details_url, wait_until="networkidle", timeout=30_000)
            # Wait for the main content to appear
            page.wait_for_selector(
                "text=Veröffentlichungsdatum, text=Veröffentlichungsdatum, .panel, #Details",
                timeout=10_000
            )
        except PWTimeout:
            pass

        html = page.content()
        metadata = _extract_metadata(html, page.url)
        tenders.append(metadata)

        print(f"  Title: {metadata.get('title')}")
        print(f"  Authority: {metadata.get('contracting_authority')}")
        print(f"  Deadline: {metadata.get('submission_deadline')}")
        print(f"  CPV: {metadata.get('cpv_code')}")
        print(f"  Reference: {metadata.get('reference')}")

        # ── Step 2: Load documents page and download ZIP ────────────────
        print(f"\nLoading documents page: {documents_url}")
        page.goto(documents_url, wait_until="networkidle", timeout=30_000)

        try:
            page.wait_for_selector(
                "a[href*='zipDownloadButton'], .filename, #collapseDocumentsDataList",
                timeout=15_000
            )
        except PWTimeout:
            pass

        # Try ZIP bundle first
        zip_sel = "a[href*='zipDownloadButton'], a.download-files, a[title*='ZIP']"
        zip_links = page.locator(zip_sel).all()
        print(f"  ZIP buttons found: {len(zip_links)}")

        for link in zip_links:
            try:
                with page.expect_download(timeout=60_000) as dl_info:
                    link.click()
                download = dl_info.value
                name = download.suggested_filename or "tender_documents.zip"
                dest = out / name
                download.save_as(str(dest))
                if dest.stat().st_size > 100:
                    downloaded_files.append(str(dest))
                    print(f"  ZIP saved: {dest.name} ({dest.stat().st_size // 1024} KB)")
                break
            except Exception as e:
                print(f"  ZIP click failed: {e}")

        # Fallback: individual download links
        if not downloaded_files:
            sel_list = [
                "a[href*='downloadLink']",
                "a[title*='herunterladen']",
                "span.glyphicon-download-alt",
            ]
            for sel in sel_list:
                links = page.locator(sel).all()
                if not links:
                    continue
                print(f"  Trying {len(links)} individual links via '{sel}'")
                for i, link in enumerate(links):
                    try:
                        with page.expect_download(timeout=20_000) as dl_info:
                            link.click()
                        dl = dl_info.value
                        name = dl.suggested_filename or f"document_{i+1}"
                        dest = out / name
                        dl.save_as(str(dest))
                        if dest.stat().st_size > 50:
                            downloaded_files.append(str(dest))
                            print(f"    [{i+1}] {dest.name} ({dest.stat().st_size // 1024} KB)")
                    except Exception as e:
                        print(f"    [{i+1}] failed: {e}")
                if downloaded_files:
                    break

        ctx.close()
        browser.close()

    # ── Step 3: Save JSON and CSV ──────────────────────────────────────
    result = {"tenders": tenders, "downloaded_files": downloaded_files}

    json_path = out / "tenders.json"
    json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved JSON: {json_path}")

    csv_path = out / "tenders.csv"
    _save_csv(tenders, csv_path)
    print(f"Saved CSV:  {csv_path}")

    print(f"\nDocuments downloaded: {len(downloaded_files)}")
    return result
