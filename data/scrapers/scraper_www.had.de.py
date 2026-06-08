"""
www.had.de — Hessisches Ausschreibungsblatt (HAD).

HAD uses a custom PHP-based portal. Tender detail pages contain
direct PDF/ZIP download links in the Unterlagen section.
Strategy: Playwright navigation → find document links → HTTP download.
"""
import os
import re
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
DOC_EXTS = {".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".gaeb", ".x81", ".x83", ".rar", ".7z"}
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
        print(f"[had] http dl failed: {e}")
        return None


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent=UA)
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)

                for sel in ["button:has-text('Akzeptieren')", "button:has-text('Alle akzeptieren')",
                             "#cookie-accept", "[id*='cookie'] button"]:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(600)
                            break
                    except Exception:
                        pass

                # HAD: click "Unterlagen" tab if present
                for tab_sel in ["a:has-text('Unterlagen')", "a:has-text('Dokumente')",
                                 "li:has-text('Unterlagen') a", "#tab_unterlagen"]:
                    try:
                        el = page.locator(tab_sel).first
                        if el.is_visible():
                            el.click()
                            page.wait_for_timeout(1500)
                            break
                    except Exception:
                        pass

                # Try "Alle herunterladen" / ZIP button
                for btn_sel in ["a:has-text('Alle herunterladen')", "button:has-text('Alle herunterladen')",
                                 "a:has-text('ZIP')", "a[href*='.zip']"]:
                    try:
                        btn = page.locator(btn_sel).first
                        if btn.is_visible():
                            with page.expect_download(timeout=25000) as dl:
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

                    for el in page.locator("a[href]").all():
                        try:
                            href = el.get_attribute("href") or ""
                            if any(href.lower().endswith(ext) for ext in DOC_EXTS):
                                p = _http_dl(urljoin(base, href), output_dir, session)
                                if p:
                                    downloaded.append(p)
                        except Exception:
                            continue

            except Exception as e:
                print(f"[had] playwright error: {e}")
            finally:
                ctx.close()
                browser.close()
    except Exception as e:
        print(f"[had] browser launch error: {e}")

    return {"downloaded_files": downloaded}
