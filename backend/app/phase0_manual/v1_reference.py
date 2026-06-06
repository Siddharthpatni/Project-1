"""
Phase 0 Manual Scraper — V1 Reference Implementation.

Strategy (in priority order):
  1. "Download All" / "Alle herunterladen" button  → single ZIP download
  2. ZIP / archive href links                       → direct download
  3. Scored document links (PDF, DOCX, etc.)        → click + HTTP fallback
  4. Buttons with onclick / data-url attributes     → click to trigger download
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from playwright.sync_api import sync_playwright

from app.utils.logger import get_logger

log = get_logger(__name__)

# ── Configuration ──────────────────────────────────────────────────────────

DOCUMENT_EXTENSIONS = frozenset({
    ".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".rar", ".7z",
    ".odt", ".ods", ".p7s", ".gaeb", ".x81", ".x83", ".d83", ".d84",
    ".ppt", ".pptx", ".txt", ".csv",
})

DOC_TEXT_KEYWORDS = [
    "unterlag", "leistungsverzeichnis", "leistungsbeschreibung",
    "ausschreibung", "vergabeunterlag", "angebotsunterlag",
    "gaeb", "download", "dokument", "alle dokumente",
    "bekanntmachung", "eigenerklärung", "fragen", "antworten",
    "unterlagen", "datei", "herunterladen", "attachment",
]

# "Download All" button text patterns — these get highest priority
DOWNLOAD_ALL_TEXTS = [
    "alle herunterladen", "alle dokumente", "alle unterlagen", "alle als zip",
    "alles herunterladen", "download all", "download zip", "zip herunterladen",
    "unterlagen herunterladen", "alle vergabeunterlagen", "gesamtpaket",
    "vergabeunterlagen herunterladen", "unterlagen als zip", "als zip",
    "alle dateien", "complete documents", "télécharger tout",
]

DOC_SKIP_TEXT = ["agb", "datenschutz", "impressum", "login", "registrierung", "cookie"]

NETSERVER_URL_TEMPLATES = [
    "https://www.vergabe24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
    "https://www.tender24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
]

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
}

_MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024  # 200 MB


# ── URL Recovery (NetServer) ───────────────────────────────────────────────

def extract_tender_id(url: str) -> str | None:
    m = re.search(r"(54321-(?:Tender|PublishingProcess)-[a-f0-9][a-f0-9\-]+)", url, re.IGNORECASE)
    return m.group(1) if m else None


def recover_url(original_url: str) -> str:
    tid = extract_tender_id(original_url)
    if not tid:
        return original_url
    for template in NETSERVER_URL_TEMPLATES:
        candidate = template.format(tid=tid)
        try:
            r = requests.get(candidate, headers=BROWSER_HEADERS, timeout=5)
            if r.status_code == 200 and len(r.text) > 1000:
                return candidate
        except requests.RequestException:
            continue
    return original_url


# ── Helpers ────────────────────────────────────────────────────────────────

def dismiss_cookies(page) -> None:
    selectors = [
        "xpath=//button[contains(.,'Akzeptieren')]",
        "xpath=//button[contains(.,'Alle akzeptieren')]",
        "xpath=//button[contains(.,'Annehmen')]",
        "xpath=//button[contains(.,'Accept')]",
        "xpath=//button[contains(.,'Zustimmen')]",
        "text=Einverstanden",
        "#accept-cookies", ".cookie-accept", "[id*=accept]",
    ]
    for sel in selectors:
        try:
            if page.is_visible(sel, timeout=400):
                page.click(sel, timeout=400)
                return
        except Exception:
            pass


def score_link(href: str, text: str | None, domain: str) -> int:
    low_href = href.lower()
    low_text = (text or "").lower().strip()

    # Hard rejects
    if any(k in low_href for k in ["/agb", "/login", "/register", "/datenschutz", "/impress"]):
        return 0
    if any(k in low_text for k in DOC_SKIP_TEXT):
        return 0

    # Highest score: "Download All" ZIP patterns in href
    if any(p in low_href for p in ["downloadall", "alleherunterladen", "download-all",
                                     "zipdownloadbutton", "downloadallbutton", "archive",
                                     "alle-dokumente", "gesamtpaket"]):
        return 10

    # Highest score: ZIP file
    if low_href.endswith(".zip") or ".zip?" in low_href:
        return 9

    score = 0
    ext = Path(urlparse(href).path).suffix.lower()
    if ext in DOCUMENT_EXTENSIONS:
        score += 3
    if any(k in low_text for k in DOC_TEXT_KEYWORDS):
        score += 2
    if any(e in low_text for e in [".pdf", ".zip", ".docx"]):
        score += 1

    return score


def _save_download(download, output_dir: str, fallback_name: str) -> str | None:
    """Save a Playwright download object, validate and return path or None."""
    name = download.suggested_filename or fallback_name
    save_path = os.path.join(output_dir, name)
    try:
        download.save_as(save_path)
        size = os.path.getsize(save_path)
        if size < 100:
            os.unlink(save_path)
            return None
        # Reject HTML error pages
        with open(save_path, "rb") as f:
            hdr = f.read(512).lower()
        if b"<html" in hdr or b"<!doctype" in hdr:
            os.unlink(save_path)
            return None
        log.info("v1_reference.saved", name=name, bytes=size)
        return save_path
    except Exception as e:
        log.debug("v1_reference.save_failed", name=name, error=str(e))
        return None


def _download_http(url: str, output_dir: str, name: str) -> str | None:
    """Stream-download a URL directly. Returns path or None."""
    save_path = os.path.join(output_dir, name)
    for attempt in range(3):
        try:
            with requests.get(url, headers=BROWSER_HEADERS, timeout=25, stream=True) as r:
                if r.status_code >= 400:
                    return None
                ct = r.headers.get("content-type", "").lower()
                if "text/html" in ct:
                    return None
                cl = r.headers.get("content-length")
                if cl and int(cl) > _MAX_DOWNLOAD_BYTES:
                    return None

                written = 0
                with open(save_path, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            written += len(chunk)
                            if written > _MAX_DOWNLOAD_BYTES:
                                os.unlink(save_path)
                                return None
                            f.write(chunk)

                if written < 200:
                    os.unlink(save_path)
                    return None
                with open(save_path, "rb") as f:
                    hdr = f.read(512).lower()
                if b"<html" in hdr or b"<!doctype" in hdr:
                    os.unlink(save_path)
                    return None
                return save_path
        except requests.RequestException as e:
            log.debug("v1_reference.http_error", url=url, attempt=attempt+1, error=str(e))
            if attempt < 2:
                time.sleep(1)
    return None


# ── Core scraper ───────────────────────────────────────────────────────────

def scrape(url: str, output_dir: str) -> list[str]:
    """
    Main entry point. Returns list of downloaded file paths.

    Priority order:
    1. Find and click "Alle herunterladen" / "Download All" button → ZIP
    2. Find ZIP/archive links and download directly
    3. Score all document links and download top matches
    """
    downloaded: list[str] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                accept_downloads=True,
                user_agent=BROWSER_HEADERS["User-Agent"],
                extra_http_headers={"Accept-Language": "de-DE,de;q=0.9,en;q=0.7"},
            )
            page = context.new_page()

            # ── 1. Load page ───────────────────────────────────────────────
            final_url = recover_url(url)
            try:
                page.goto(final_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
                dismiss_cookies(page)
                # Extra wait for JS-heavy portals (Angular, React)
                page.wait_for_timeout(1500)
            except Exception as e:
                log.warning("v1_reference.goto_failed", url=final_url, error=str(e))
                return []

            # ── 2. Expand tree grids ───────────────────────────────────────
            for _ in range(8):
                try:
                    pluses = page.query_selector_all("img[src*='plus']")
                    if not pluses:
                        break
                    clicked = False
                    for el in pluses:
                        try:
                            if el.is_visible():
                                el.click(force=True)
                                clicked = True
                        except Exception:
                            pass
                    if not clicked:
                        break
                    page.wait_for_timeout(1200)
                except Exception:
                    break

            # ── 3. PRIORITY: "Download All" button/link ─────────────────────
            try:
                dl_all = _find_download_all(page)
                if dl_all:
                    log.info("v1_reference.download_all_found", url=url)
                    with page.expect_download(timeout=30000) as di:
                        dl_all.click(force=True)
                    saved = _save_download(di.value, output_dir, "all_documents.zip")
                    if saved:
                        downloaded.append(saved)
                        log.info("v1_reference.download_all_success", path=saved)
                        return downloaded  # ZIP contains everything — we're done
            except Exception as e:
                log.debug("v1_reference.download_all_failed", error=str(e))

            # ── 4. Collect all scored candidates ──────────────────────────
            candidates: list[tuple[str, int, object]] = []
            seen_urls: set[str] = set()

            # a) anchor tags
            try:
                for link in page.query_selector_all("a[href]"):
                    try:
                        href = link.get_attribute("href") or ""
                        text = link.inner_text()
                        if not href or href.startswith("#") or href.startswith("javascript"):
                            continue
                        full = urljoin(page.url, href)
                        if full in seen_urls:
                            continue
                        s = score_link(full, text, urlparse(page.url).netloc)
                        if s > 0:
                            seen_urls.add(full)
                            candidates.append((full, s, link))
                    except Exception:
                        continue
            except Exception as e:
                log.debug("v1_reference.link_query_error", error=str(e))

            # b) buttons / inputs that might trigger downloads
            try:
                for btn in page.query_selector_all("button, input[type=button], input[type=submit]"):
                    try:
                        text = (btn.inner_text() or btn.get_attribute("value") or "").lower()
                        if any(k in text for k in ["download", "herunterladen", "unterlag", "zip", "dokument"]):
                            candidates.append(("button:" + text[:40], 4, btn))
                    except Exception:
                        continue
            except Exception:
                pass

            candidates.sort(key=lambda x: -x[1])

            # ── 5. Download candidates ─────────────────────────────────────
            content_hashes: set[str] = set()

            for i, (doc_url, score, element) in enumerate(candidates[:80]):
                if len(downloaded) >= 50:
                    break

                # Try Playwright click → download event
                try:
                    with page.expect_download(timeout=8000) as di:
                        element.click(force=True)
                    saved = _save_download(di.value, output_dir, f"doc_{i}.bin")
                    if saved:
                        _add_if_new(saved, content_hashes, downloaded)
                    continue
                except Exception:
                    pass

                # Skip buttons — they only work via click
                if str(doc_url).startswith("button:"):
                    continue

                # HTTP fallback for direct file URLs
                try:
                    url_ext = Path(urlparse(doc_url).path).suffix.lower()
                    if url_ext not in DOCUMENT_EXTENSIONS and score < 3:
                        continue
                    ext = url_ext if url_ext in DOCUMENT_EXTENSIONS else ".bin"
                    name = f"doc_{i}_{hashlib.md5(doc_url.encode()).hexdigest()[:6]}{ext}"
                    saved = _download_http(doc_url, output_dir, name)
                    if saved:
                        _add_if_new(saved, content_hashes, downloaded)
                except Exception as e:
                    log.debug("v1_reference.http_fallback_error", url=doc_url, error=str(e))

        except Exception as e:
            log.error("v1_reference.fatal", url=url, error=str(e))
        finally:
            try:
                browser.close()
            except Exception:
                pass

    log.info("v1_reference.done", url=url, files=len(downloaded))
    return downloaded


def _find_download_all(page):
    """
    Find a "Download All" / "Alle herunterladen" element.
    Returns the element or None.
    """
    # 1. Buttons with matching text
    for btn in page.query_selector_all("button, a, input[type=button]"):
        try:
            text = (btn.inner_text() or btn.get_attribute("value") or "").lower().strip()
            if any(t in text for t in DOWNLOAD_ALL_TEXTS) and btn.is_visible():
                return btn
        except Exception:
            continue

    # 2. Links with ZIP in href or download-all patterns
    for a in page.query_selector_all("a[href]"):
        try:
            href = (a.get_attribute("href") or "").lower()
            text = a.inner_text().lower()
            if not a.is_visible():
                continue
            if any(p in href for p in ["downloadall", "alleherunterladen", "download-all",
                                        "zipdownloadbutton", "downloadallbutton",
                                        "archive", "gesamtpaket"]):
                return a
            if any(t in text for t in DOWNLOAD_ALL_TEXTS):
                return a
        except Exception:
            continue

    return None


def _add_if_new(path: str, hashes: set, downloaded: list) -> None:
    """Add path to downloaded list if it's not a duplicate (SHA256 of first 4 KB)."""
    try:
        with open(path, "rb") as f:
            h = hashlib.sha256(f.read(4096)).hexdigest()
        if h in hashes:
            try:
                os.unlink(path)
            except OSError:
                pass
        else:
            hashes.add(h)
            downloaded.append(path)
    except Exception:
        downloaded.append(path)


if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else ""
    out = "./test_downloads"
    os.makedirs(out, exist_ok=True)
    files = scrape(test_url, out)
    print(f"Downloaded: {files}")
