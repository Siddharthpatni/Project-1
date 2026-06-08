"""
www.kvb.de — KVB (Kassenärztliche Vereinigung Bayern) procurement portal.

KVB uses an embedded iframe or redirect to their procurement module.
The URL in the dataset is usually the procurement module URL itself.
Strategy:
  1. Try direct HTTP download for any ZIP/PDF in the URL path.
  2. Navigate with Playwright, find document section, extract links.
"""
import os
import re
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
DOC_EXTS = {".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".gaeb", ".x81", ".rar", ".7z"}
MAX_BYTES = 200 * 1024 * 1024


def _http_dl(url: str, output_dir: str, session=None) -> str | None:
    try:
        getter = session.get if session else requests.get
        r = getter(url, stream=True, timeout=20,
                   headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"},
                   allow_redirects=True)
        if r.status_code >= 400:
            return None
        ct = r.headers.get("content-type", "").lower()
        if "html" in ct:
            return None
        fname = Path(urlparse(url).path).name.split("?")[0] or "document.pdf"
        dest = Path(output_dir) / fname
        size = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    dest.unlink(missing_ok=True)
                    return None
                f.write(chunk)
        return str(dest) if dest.stat().st_size > 0 else None
    except Exception as e:
        print(f"[kvb] http dl failed: {e}")
        return None


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    # Check if URL already points to a direct document
    ext = Path(parsed.path).suffix.lower()
    if ext in DOC_EXTS:
        p = _http_dl(url, output_dir)
        if p:
            return {"downloaded_files": [p]}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent=UA)
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                # Follow any iframe redirect to the actual content
                frames = page.frames
                target_page = page
                for frame in frames:
                    if frame != page.main_frame and "vergabe" in (frame.url or "").lower():
                        try:
                            frame_url = frame.url
                            target_page = ctx.new_page()
                            target_page.goto(frame_url, wait_until="domcontentloaded", timeout=20000)
                            page.wait_for_timeout(2000)
                            break
                        except Exception:
                            target_page = page

                # Cookie consent
                for sel in ["button:has-text('Akzeptieren')", "button:has-text('Alle akzeptieren')",
                             "[id*='cookie'] button"]:
                    try:
                        btn = target_page.locator(sel).first
                        if btn.is_visible():
                            btn.click()
                            target_page.wait_for_timeout(600)
                            break
                    except Exception:
                        pass

                # Navigate to documents section
                for tab_sel in ["a:has-text('Unterlagen')", "a:has-text('Dokumente')",
                                 "a:has-text('Ausschreibungsunterlagen')", "[id*='dokument']"]:
                    try:
                        el = target_page.locator(tab_sel).first
                        if el.is_visible():
                            el.click()
                            target_page.wait_for_timeout(1500)
                            break
                    except Exception:
                        pass

                # Try download buttons
                for btn_sel in ["a:has-text('Alle herunterladen')", "button:has-text('Alle herunterladen')",
                                 "a:has-text('ZIP herunterladen')", "a[href*='.zip']"]:
                    try:
                        btn = target_page.locator(btn_sel).first
                        if btn.is_visible():
                            btn.scroll_into_view_if_needed()
                            with target_page.expect_download(timeout=25000) as dl:
                                btn.click()
                            d = dl.value
                            dest = Path(output_dir) / (d.suggested_filename or "documents.zip")
                            d.save_as(str(dest))
                            downloaded.append(str(dest))
                            break
                    except Exception:
                        continue

                if not downloaded:
                    session = requests.Session()
                    for c in ctx.cookies():
                        session.cookies.set(c["name"], c["value"], domain=c.get("domain"))

                    page_base = f"{urlparse(target_page.url).scheme}://{urlparse(target_page.url).netloc}"
                    for el in target_page.locator("a[href]").all():
                        try:
                            href = el.get_attribute("href") or ""
                            if any(href.lower().endswith(ext) for ext in DOC_EXTS):
                                p = _http_dl(urljoin(page_base, href), output_dir, session)
                                if p:
                                    downloaded.append(p)
                        except Exception:
                            continue

            except Exception as e:
                print(f"[kvb] playwright error: {e}")
            finally:
                ctx.close()
                browser.close()
    except Exception as e:
        print(f"[kvb] browser launch error: {e}")

    return {"downloaded_files": downloaded}
