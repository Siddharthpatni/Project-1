"""
Generic NetServer Publication Scraper — covers ALL NetServer PublicationControllerServlet domains.

Works for: vergabe.muenchen.de, vergabe.deges.de, vergabe.fraunhofer.de,
           vergabe.landbw.de, saarvpsl.vmstart.de, www.ausschreibungen.ls.brandenburg.de,
           www.deutsche-rentenversicherung-bund.de, www.evergabe.sachsen.de,
           www.sachsen-vergabe.de, www.vergabemarktplatz-mv.de,
           www.vergabe.stadt-frankfurt.de, and any /NetServer/PublicationControllerServlet URL.

Strategy:
  1. Navigate to the publication detail page.
  2. Find all document download links (function=_DownloadDocument or GetDocumentFile).
  3. Intercept any file downloads triggered by clicking download buttons.
  4. If nothing found via links, try the _DownloadTenderDocuments ZIP endpoint.
  5. Return all downloaded files.
"""
import os
import re
import requests
import hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs, urlsplit
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

DOC_EXTS = {
    ".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ods", ".odt",
    ".gaeb", ".x81", ".x83", ".ppt", ".pptx", ".txt", ".rar", ".7z",
    ".p7s", ".d83", ".d84", ".csv", ".xml",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
MAX_FILE_BYTES = 200 * 1024 * 1024  # 200 MB


def _http_download(url: str, output_dir: str, session=None) -> str | None:
    """Direct HTTP download — used for document links that don't need browser."""
    try:
        hdrs = {"User-Agent": UA, "Accept-Language": "de-DE,de;q=0.9,en;q=0.7"}
        getter = session.get if session else requests.get
        r = getter(url, stream=True, timeout=20, headers=hdrs, allow_redirects=True)
        if r.status_code >= 400:
            return None
        ct = r.headers.get("content-type", "").lower()
        if "html" in ct or "text/plain" in ct:
            return None

        # Determine filename
        filename = Path(urlparse(url).path).name.split("?")[0]
        if not filename or "." not in filename:
            cd = r.headers.get("content-disposition", "")
            m = re.findall(r'filename[^;=\n]*=[\"\']?([^\"\';\n]+)', cd)
            filename = m[0].strip('"').strip() if m else hashlib.md5(url.encode()).hexdigest() + ".bin"

        dest = Path(output_dir) / filename
        size = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    dest.unlink(missing_ok=True)
                    return None
                f.write(chunk)

        if dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
            return None
        return str(dest)
    except Exception as e:
        print(f"[netserver_pub] http download failed: {e}")
        return None


def _extract_doc_links(page, base_url: str) -> list[str]:
    """
    Extract all document download links from the NetServer publication page.
    NetServer uses several link patterns:
      - function=_DownloadDocument&DocumentID=...
      - function=GetDocumentFile&TWOID=...&DocumentID=...
      - Direct href to PDF/ZIP/DOCX files
    """
    links = []
    try:
        # Pattern 1: explicit download function links
        for sel in [
            "a[href*='_DownloadDocument']",
            "a[href*='GetDocumentFile']",
            "a[href*='function=Download']",
            "a[href*='download']",
            "a[href*='Download']",
        ]:
            for el in page.locator(sel).all():
                href = el.get_attribute("href") or ""
                if href:
                    links.append(urljoin(base_url, href))

        # Pattern 2: any link whose text or title suggests a document
        for el in page.locator("a").all():
            href = el.get_attribute("href") or ""
            text = (el.inner_text() or "").strip().lower()
            title = (el.get_attribute("title") or "").lower()
            if href and (
                any(ext in href.lower() for ext in DOC_EXTS) or
                any(kw in text for kw in ["download", "herunterladen", "dokument", "datei", "unterlag"]) or
                any(kw in title for kw in ["download", "dokument", "datei"])
            ):
                full = urljoin(base_url, href)
                if full not in links:
                    links.append(full)

    except Exception as e:
        print(f"[netserver_pub] link extraction error: {e}")

    # Deduplicate while preserving order
    return list(dict.fromkeys(links))


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    downloaded = []

    # Extract the TenderOID/TWOID from URL for fallback ZIP attempt
    oid = None
    for param in ("TenderOID", "TWOID"):
        m = re.search(rf"{param}=([^&]+)", url)
        if m:
            oid = m.group(1)
            break
    if not oid:
        m = re.search(r"(54321-(?:Tender|PublishingProcess)-[a-f0-9\-]+)", url, re.IGNORECASE)
        oid = m.group(1) if m else None

    # Build base URLs for this NetServer instance
    parts = urlsplit(url)
    ns_path = re.search(r"(/.*?/NetServer/)", parts.path, re.IGNORECASE)
    ns_base = f"{parts.scheme}://{parts.netloc}{ns_path.group(1)}" if ns_path else f"{parts.scheme}://{parts.netloc}/NetServer/"
    base_url = f"{parts.scheme}://{parts.netloc}"

    # === Phase 1: Try direct ZIP download (fastest) ===
    if oid:
        zip_candidates = [
            f"{ns_base}TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={oid}",
            f"{ns_base}PublicationControllerServlet?function=GetDocumentFile&TWOID={oid}",
            f"{ns_base}TenderingProcedureDetails?function=_DownloadPublicationDocuments&TenderOID={oid}",
        ]
        session = requests.Session()
        session.headers["User-Agent"] = UA
        for zip_url in zip_candidates:
            path = _http_download(zip_url, output_dir, session)
            if path:
                downloaded.append(path)
                print(f"[netserver_pub] ZIP download succeeded: {zip_url}")
                return {"downloaded_files": downloaded}

    # === Phase 2: Playwright navigation + document link extraction ===
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            ctx = browser.new_context(
                accept_downloads=True,
                locale="de-DE",
                user_agent=UA,
            )
            page = ctx.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(2000)

                # Dismiss cookie banners
                for sel in [
                    "button:has-text('Akzeptieren')",
                    "button:has-text('Alle akzeptieren')",
                    "button:has-text('Zustimmen')",
                    "#cookie-accept",
                    "[id*='cookie'] button",
                ]:
                    try:
                        btn = page.locator(sel).first
                        if btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(800)
                            break
                    except Exception:
                        pass

                # Try "Alle herunterladen" / "Download All" button first
                for btn_sel in [
                    "button:has-text('Alle herunterladen')",
                    "a:has-text('Alle herunterladen')",
                    "button:has-text('Alle Dokumente herunterladen')",
                    "button:has-text('Download all')",
                    "a:has-text('Alle als ZIP')",
                    "[title*='herunterladen']",
                ]:
                    try:
                        btn = page.locator(btn_sel).first
                        if btn.is_visible():
                            btn.scroll_into_view_if_needed()
                            with page.expect_download(timeout=25000) as dl_info:
                                btn.click()
                            dl = dl_info.value
                            fname = dl.suggested_filename or "documents.zip"
                            dest = Path(output_dir) / fname
                            dl.save_as(str(dest))
                            downloaded.append(str(dest))
                            print(f"[netserver_pub] 'Alle herunterladen' succeeded: {fname}")
                            break
                    except Exception:
                        continue

                if not downloaded:
                    # Extract individual document links and download each
                    doc_links = _extract_doc_links(page, base_url)
                    print(f"[netserver_pub] found {len(doc_links)} document links")

                    session = requests.Session()
                    # Copy browser cookies to requests session for auth continuity
                    for cookie in ctx.cookies():
                        session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"))

                    for link in doc_links[:30]:  # cap at 30 files per tender
                        path = _http_download(link, output_dir, session)
                        if path:
                            downloaded.append(path)

                    # If HTTP didn't work, try clicking each download button in browser
                    if not downloaded:
                        for btn_sel in [
                            "a[href*='_DownloadDocument']",
                            "a[href*='GetDocumentFile']",
                            "button[onclick*='download']",
                        ]:
                            try:
                                buttons = page.locator(btn_sel).all()
                                for btn in buttons[:10]:
                                    try:
                                        with page.expect_download(timeout=15000) as dl_info:
                                            btn.click()
                                        dl = dl_info.value
                                        fname = dl.suggested_filename or "document.pdf"
                                        dest = Path(output_dir) / fname
                                        dl.save_as(str(dest))
                                        downloaded.append(str(dest))
                                    except Exception:
                                        continue
                            except Exception:
                                continue

            except Exception as e:
                print(f"[netserver_pub] playwright error: {e}")
            finally:
                ctx.close()
                browser.close()

    except Exception as e:
        print(f"[netserver_pub] browser launch error: {e}")

    return {"downloaded_files": downloaded}
