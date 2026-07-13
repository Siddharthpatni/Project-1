"""
www.evergabe.nrw.de — NRW Vergabemarktplatz.

Two URL types exist on this portal:
  1. /VMPSatellite/notice/<ID>  — deterministic ZIP download (like all Satellite family)
  2. /evergabe.bieter/... deeplinks — Cosinex Angular app requiring vendor login

Strategy:
  - VMPSatellite URLs: build ZIP URL directly (no browser, fastest)
  - Deeplink/Angular URLs: try "Alle herunterladen" button after Angular renders
"""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
MAX_BYTES = 200 * 1024 * 1024


def _build_vmp_zip_url(url: str) -> str | None:
    m = re.search(
        r"/(?:VMPSatellite|Satellite|Vergabe)/(?:notice|public/company/project)/([A-Z0-9a-z]+)",
        url, re.IGNORECASE,
    )
    if not m:
        return None
    project_id = m.group(1)
    parts = urlsplit(url)
    prefix = "VMPSatellite" if "/VMPSatellite/" in url else ("Vergabe" if "/Vergabe/" in url else "Satellite")
    return (
        f"{parts.scheme}://{parts.netloc}"
        f"/{prefix}/public/company/project/{project_id}"
        f"/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
    )


def _http_download(url: str, output_dir: str) -> str | None:
    try:
        r = requests.get(
            url, stream=True, timeout=30,
            headers={"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9"},
            allow_redirects=True,
        )
        if r.status_code >= 400:
            return None
        ct = r.headers.get("content-type", "").lower()
        if "html" in ct:
            return None
        name = Path(url.split("?")[0]).name or "documents.zip"
        dest = Path(output_dir) / name
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
        print(f"[evergabe_nrw] http download failed: {e}")
        return None


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    downloaded = []

    # ── Path 1: VMPSatellite deterministic (no browser needed) ────────────────
    zip_url = _build_vmp_zip_url(url)
    if zip_url:
        path = _http_download(zip_url, output_dir)
        if path:
            downloaded.append(path)
            return {"downloaded_files": downloaded}

    # ── Path 2: Cosinex Angular deeplink — browser automation ─────────────────
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent=UA)
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except PWTimeout:
                    pass
                page.wait_for_timeout(5000)

                for sel in [
                    "button:has-text('Akzeptieren')", "button:has-text('Alle akzeptieren')",
                    "button:has-text('Zustimmen')", "[id*='cookie'] button",
                ]:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(800)
                            break
                    except Exception:
                        pass

                for tab_sel in [
                    "button:has-text('Vergabeunterlagen')", "a:has-text('Vergabeunterlagen')",
                    "[role='tab']:has-text('Unterlagen')", "button:has-text('Dokumente')",
                ]:
                    try:
                        tab = page.locator(tab_sel).first
                        if tab.is_visible():
                            tab.click()
                            page.wait_for_timeout(3000)
                            break
                    except Exception:
                        pass

                for btn_sel in [
                    "button:has-text('Alle herunterladen')", "a:has-text('Alle herunterladen')",
                    "button:has-text('Herunterladen')", "button:has-text('Download all')",
                ]:
                    try:
                        btn = page.locator(btn_sel).first
                        if not btn.is_visible():
                            continue
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

            except Exception as e:
                print(f"[evergabe_nrw] playwright error: {e}")
            finally:
                ctx.close()
                browser.close()
    except Exception as e:
        print(f"[evergabe_nrw] browser launch error: {e}")

    return {"downloaded_files": downloaded}
