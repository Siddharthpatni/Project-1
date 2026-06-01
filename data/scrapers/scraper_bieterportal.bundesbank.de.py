# Generic eVergabe 4.9 / Cosinex Angular scraper
# Works for: bieterportal.noncd.db.de, ausschreibungen.kfw.de,
#             bieter.ehealth-evergabe.de, vergabemarktplatz.brandenburg.de,
#             vergabe.muenchen.de, www.evergabe.bayern.de, and any site with
#             /evergabe.bieter/api/supplier/external/deeplink/ in the path.
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    downloaded_files = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            accept_downloads=True,
            locale="de-DE",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = ctx.new_page()

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Angular apps need extra time to render after DOM load
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PWTimeout:
                pass
            page.wait_for_timeout(5000)

            # Dismiss cookie consent banners
            for sel in [
                "button:has-text('Akzeptieren')",
                "button:has-text('Alle akzeptieren')",
                "button:has-text('Zustimmen')",
                "button:has-text('Accept')",
                "[id*='cookie'] button",
                "[class*='consent'] button",
            ]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(1000)
                        break
                except Exception:
                    pass

            # Try "Alle herunterladen" (ZIP of all documents)
            for btn_sel in [
                "button:has-text('Alle herunterladen')",
                "button:has-text('Herunterladen')",
                "button:has-text('Download all')",
                "button:has-text('Alle Dokumente')",
                "a:has-text('Alle herunterladen')",
                "[class*='download']:has-text('alle')",
            ]:
                try:
                    btn = page.locator(btn_sel).first
                    if not btn.is_visible():
                        continue
                    btn.scroll_into_view_if_needed()
                    with page.expect_download(timeout=30000) as dl:
                        btn.click()
                    download = dl.value
                    dest = Path(output_dir) / (download.suggested_filename or "documents.zip")
                    download.save_as(str(dest))
                    downloaded_files.append(str(dest))
                    break  # ZIP found — done
                except Exception:
                    continue

            # Fallback: look for "Vergabeunterlagen" tab first, then retry
            if not downloaded_files:
                for tab_sel in [
                    "button:has-text('Vergabeunterlagen')",
                    "a:has-text('Vergabeunterlagen')",
                    "button:has-text('Dokumente')",
                    "[role='tab']:has-text('Unterlagen')",
                ]:
                    try:
                        tab = page.locator(tab_sel).first
                        if tab.is_visible():
                            tab.click()
                            page.wait_for_timeout(3000)
                            break
                    except Exception:
                        continue

                # Retry download after tab click
                for btn_sel in [
                    "button:has-text('Alle herunterladen')",
                    "button:has-text('Herunterladen')",
                    "a:has-text('Alle herunterladen')",
                ]:
                    try:
                        btn = page.locator(btn_sel).first
                        if not btn.is_visible():
                            continue
                        btn.scroll_into_view_if_needed()
                        with page.expect_download(timeout=30000) as dl:
                            btn.click()
                        download = dl.value
                        dest = Path(output_dir) / (download.suggested_filename or "documents.zip")
                        download.save_as(str(dest))
                        downloaded_files.append(str(dest))
                        break
                    except Exception:
                        continue

        except Exception as e:
            print(f"[evergabe_cosinex] error: {e}")
        finally:
            ctx.close()
            browser.close()

    return {"downloaded_files": downloaded_files}
