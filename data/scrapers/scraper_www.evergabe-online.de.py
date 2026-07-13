"""
evergabe-online.de — Apache Wicket procurement portal. FIXED version.
Strategy: navigate → find Unterlagen tab → click Alle herunterladen → ZIP.
Fallback: individual PDF/document links.
"""
import os, re, requests
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"

def _http_dl(url, out, session=None):
    try:
        getter = session.get if session else requests.get
        r = getter(url, stream=True, timeout=20, headers={"User-Agent": UA}, allow_redirects=True)
        if r.status_code >= 400 or "html" in r.headers.get("content-type","").lower(): return None
        fname = Path(urlparse(url).path).name or "doc.bin"
        dest = Path(out) / fname
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536): f.write(chunk)
        return str(dest) if dest.stat().st_size > 0 else None
    except Exception: return None

def scrape(url, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent=UA)
        page = ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)
            # Cookie consent
            for sel in ["button:has-text('Alle akzeptieren')", "button:has-text('Akzeptieren')"]:
                try:
                    if page.locator(sel).first.is_visible(): page.locator(sel).first.click(); break
                except Exception: pass
            # Unterlagen tab
            for sel in ["a:has-text('Unterlagen')", "a:has-text('Dokumente')", "a[href*='dokument']", "a[href*='unterlag']"]:
                try:
                    el = page.locator(sel).first
                    if el.is_visible(): el.click(); page.wait_for_timeout(2000); break
                except Exception: pass
            # ZIP button
            for sel in ["a.zipDownloadButton", "a:has-text('Alle herunterladen')", "button:has-text('Alle herunterladen')", "a[href*='zipDownload']", "input[value*='herunterladen']"]:
                try:
                    btn = page.locator(sel).first
                    if btn.is_visible():
                        with page.expect_download(timeout=30000) as dl: btn.click()
                        d = dl.value; dest = Path(output_dir)/(d.suggested_filename or "docs.zip"); d.save_as(str(dest)); downloaded.append(str(dest)); break
                except Exception: continue
            # Individual links fallback
            if not downloaded:
                session = requests.Session()
                [session.cookies.set(c["name"],c["value"],domain=c.get("domain")) for c in ctx.cookies()]
                base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                for el in page.locator("a").all():
                    href = el.get_attribute("href") or ""
                    if any(ext in href.lower() for ext in [".pdf",".zip",".docx",".doc",".xlsx",".rar"]):
                        p = _http_dl(urljoin(base,href), output_dir, session)
                        if p: downloaded.append(p)
        except Exception as e: print(f"[evergabe-online] {e}")
        finally: ctx.close(); browser.close()
    return {"downloaded_files": downloaded}
