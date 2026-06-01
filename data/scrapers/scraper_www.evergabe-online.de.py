# evergabe-online.de (Apache Wicket) — downloads ZIP via zipDownloadButton
import os
import html
from pathlib import Path
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    downloaded_files = []

    # Extract tender ID from URL — accepts both tenderdetails and tenderdocuments URLs
    import re
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(url).query)
    tender_id = (qs.get("id") or [None])[0]

    BASE = "https://www.evergabe-online.de"
    doc_url = f"{BASE}/tenderdocuments.html?id={tender_id}" if tender_id else url

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            accept_downloads=True, locale="de-DE",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = ctx.new_page()
        try:
            page.goto(doc_url, wait_until="networkidle", timeout=30000)

            # ZIP bundle via zipDownloadButton (href may have HTML entities)
            zip_links = page.locator("a[href*='zipDownloadButton'], a[href*='downloadAllButton']").all()
            for link in zip_links:
                try:
                    raw_href = link.get_attribute("href") or ""
                    zip_href = html.unescape(raw_href)
                    abs_url = urljoin(BASE, zip_href)
                    with page.expect_download(timeout=60000) as dl:
                        link.click()
                    download = dl.value
                    dest = Path(output_dir) / (download.suggested_filename or "tender_documents.zip")
                    download.save_as(str(dest))
                    downloaded_files.append(str(dest))
                    break
                except Exception:
                    continue

            # Fallback: individual download links
            if not downloaded_files:
                for sel in ["a[href*='downloadLink']", "a[title*='herunterladen']"]:
                    links = page.locator(sel).all()
                    for link in links:
                        try:
                            with page.expect_download(timeout=20000) as dl:
                                link.click()
                            download = dl.value
                            dest = Path(output_dir) / (download.suggested_filename or "document")
                            download.save_as(str(dest))
                            if dest.stat().st_size > 50:
                                downloaded_files.append(str(dest))
                        except Exception:
                            continue
                    if downloaded_files:
                        break

        except Exception as e:
            print(f"[evergabe_online] error: {e}")
        finally:
            ctx.close()
            browser.close()

    return {"downloaded_files": downloaded_files}
