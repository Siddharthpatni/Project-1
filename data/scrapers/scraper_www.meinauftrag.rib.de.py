"""
www.meinauftrag.rib.de — RIB iTWO Tender procurement portal.

RIB iTWO uses a tree-based file browser. Tender documents are nested in
collapsible tree nodes. Strategy:
  1. Expand all tree nodes (click + icons repeatedly).
  2. Collect all leaf-node document links.
  3. Download each via HTTP (browser cookies forwarded for session auth).
  4. Fallback: "Alle herunterladen" button if present.
"""
import os
import re
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
DOC_EXTS = {".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".gaeb", ".x81", ".x83", ".rar", ".7z", ".p7s"}
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
        fname = Path(urlparse(url).path).name.split("?")[0]
        if not fname or "." not in fname:
            cd = r.headers.get("content-disposition", "")
            m = re.findall(r'filename[^;=\n]*=[\"\']?([^\"\';\n]+)', cd)
            fname = m[0].strip('"').strip() if m else "document.bin"
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
        print(f"[rib_meinauftrag] http dl failed: {e}")
        return None


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    downloaded = []
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent=UA)
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                for sel in ["button:has-text('Akzeptieren')", "button:has-text('Alle akzeptieren')",
                             "[id*='cookie'] button"]:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(600)
                            break
                    except Exception:
                        pass

                # Navigate to Vergabeunterlagen / Dokumente section
                for tab_sel in ["a:has-text('Vergabeunterlagen')", "a:has-text('Unterlagen')",
                                 "a:has-text('Dokumente')", "[id*='unterlag']",
                                 "li:has-text('Unterlagen') a"]:
                    try:
                        el = page.locator(tab_sel).first
                        if el.is_visible():
                            el.click()
                            page.wait_for_timeout(2000)
                            break
                    except Exception:
                        pass

                # Expand RIB tree grid: click all collapse/expand icons
                for _ in range(8):
                    clicked = False
                    for expand_sel in [
                        "img[src*='plus']", "img[src*='expand']",
                        "span.tree-expand", ".tree-node-collapsed",
                        "[class*='collapsed']", "td.tree-icon:not([class*='expanded'])",
                    ]:
                        try:
                            icons = page.locator(expand_sel).all()
                            for icon in icons[:20]:
                                try:
                                    if icon.is_visible():
                                        icon.click(force=True)
                                        clicked = True
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    if clicked:
                        page.wait_for_timeout(1500)
                    else:
                        break

                # Try "Alle herunterladen" first
                for btn_sel in ["button:has-text('Alle herunterladen')", "a:has-text('Alle herunterladen')",
                                 "button:has-text('Download all')", "a.downloadAll"]:
                    try:
                        btn = page.locator(btn_sel).first
                        if btn.is_visible():
                            btn.scroll_into_view_if_needed()
                            with page.expect_download(timeout=30000) as dl:
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

                    seen = set()
                    for el in page.locator("a[href]").all():
                        try:
                            href = el.get_attribute("href") or ""
                            full = urljoin(base, href)
                            if full in seen:
                                continue
                            ext = Path(urlparse(full).path).suffix.lower()
                            if ext in DOC_EXTS:
                                seen.add(full)
                                p = _http_dl(full, output_dir, session)
                                if p:
                                    downloaded.append(p)
                        except Exception:
                            continue

            except Exception as e:
                print(f"[rib_meinauftrag] playwright error: {e}")
            finally:
                ctx.close()
                browser.close()
    except Exception as e:
        print(f"[rib_meinauftrag] browser launch error: {e}")

    return {"downloaded_files": downloaded}
