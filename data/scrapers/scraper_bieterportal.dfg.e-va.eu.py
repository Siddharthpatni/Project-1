# e-VA Bieterportal (bieterportal.*.e-va.eu) — Angular-based tender portal
# URL pattern: /bundde?data=<base64-json>
import os, json, base64
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout


def _decode_data_param(url: str) -> dict:
    from urllib.parse import urlparse, parse_qs, unquote
    qs = parse_qs(urlparse(url).query)
    raw = (qs.get("data") or [None])[0]
    if not raw:
        return {}
    try:
        return json.loads(base64.b64decode(raw + "==").decode())
    except Exception:
        return {}


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    downloaded_files = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            accept_downloads=True, locale="de-DE",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        )
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PWTimeout:
                pass
            page.wait_for_timeout(5000)

            # Dismiss cookie banners
            for sel in ["button:has-text('Akzeptieren')", "button:has-text('Zustimmen')", "button:has-text('Accept')"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible():
                        btn.click(); page.wait_for_timeout(1000); break
                except Exception:
                    pass

            # Try download buttons
            for btn_sel in [
                "button:has-text('Alle herunterladen')",
                "button:has-text('Vergabeunterlagen herunterladen')",
                "a:has-text('Vergabeunterlagen')",
                "button:has-text('Unterlagen')",
                "[class*='download']",
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
            print(f"[e_va_bieterportal] error: {e}")
        finally:
            ctx.close()
            browser.close()

    return {"downloaded_files": downloaded_files}
