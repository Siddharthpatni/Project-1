"""
Live document fetcher — downloads documents directly from a tender URL
without relying on previously stored S3/MinIO objects.

Used as a fallback in the extraction trigger when no documents are in storage
(e.g. the scraping job failed or the documents were deleted from MinIO).

Strategy per platform:
  DTVP / NetServer  → build deterministic ZIP URL and download directly
  Direct file URL   → stream the file
  Unknown portal    → HEAD-check the URL; if it returns a document, download it
                      otherwise try to find a direct PDF/ZIP link in the page HTML

No Playwright required — this is a pure HTTP approach designed for speed.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import requests

from app.phase3_integration import platform_classifier
from app.phase1_llm_scraper.document_validator import is_real_document_file
from app.utils.logger import get_logger

log = get_logger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/zip,application/pdf,*/*",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
}
_MAX_BYTES = 200 * 1024 * 1024   # 200 MB
_TIMEOUT   = 30


def fetch_documents(url: str) -> list[str]:
    """
    Download all tender documents reachable from *url* without a browser.
    Returns a list of local temp file paths (caller must delete them).
    """
    platform = platform_classifier.classify_url(url)
    log.info("live_fetcher.start", url=url, platform=platform)

    # 1. Deterministic platforms: build the ZIP URL directly
    if platform_classifier.is_deterministic(platform):
        zip_url = platform_classifier.build_download_url(platform, url)
        if zip_url:
            log.info("live_fetcher.deterministic_zip", url=zip_url)
            path = _download_url(zip_url, suffix=".zip")
            if path:
                return [path]
            log.warning("live_fetcher.deterministic_failed", zip_url=zip_url)

    # 2. URL already points at a file (PDF/ZIP/DOCX)
    from urllib.parse import urlsplit
    parsed_path = urlsplit(url).path.lower()
    direct_exts = (".pdf", ".zip", ".docx", ".doc", ".xlsx", ".xls", ".rar", ".7z")
    if any(parsed_path.endswith(ext) for ext in direct_exts):
        path = _download_url(url)
        if path:
            return [path]

    # 3. Fetch the page HTML and look for document links
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT, verify=True)
        html = resp.text
    except requests.RequestException as e:
        log.warning("live_fetcher.page_fetch_failed", url=url, error=str(e))
        return []

    links = _extract_doc_links(html, url)
    log.info("live_fetcher.found_links", url=url, count=len(links))

    downloaded: list[str] = []
    for link_url in links[:20]:   # cap at 20 links
        path = _download_url(link_url)
        if path:
            downloaded.append(path)

    return downloaded


def _download_url(url: str, suffix: str | None = None) -> str | None:
    """Stream-download a URL to a temp file. Returns path or None on failure."""
    try:
        with requests.get(
            url, headers=_HEADERS, stream=True,
            timeout=_TIMEOUT, allow_redirects=True, verify=True
        ) as r:
            if r.status_code >= 400:
                log.warning("live_fetcher.bad_status", url=url, status=r.status_code)
                return None

            # Detect suffix from Content-Type or URL
            ct = r.headers.get("Content-Type", "").lower()
            if suffix is None:
                if "zip" in ct or url.lower().endswith(".zip"):
                    suffix = ".zip"
                elif "pdf" in ct or url.lower().endswith(".pdf"):
                    suffix = ".pdf"
                elif "msword" in ct or "wordprocessing" in ct:
                    suffix = ".docx"
                else:
                    from urllib.parse import urlsplit
                    url_suffix = Path(urlsplit(url).path).suffix.lower()
                    suffix = url_suffix if url_suffix else ".bin"

            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            written = 0
            try:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        written += len(chunk)
                        if written > _MAX_BYTES:
                            log.warning("live_fetcher.too_large", url=url)
                            tmp.close()
                            Path(tmp.name).unlink(missing_ok=True)
                            return None
                        tmp.write(chunk)
                tmp.close()
            except Exception as e:
                tmp.close()
                Path(tmp.name).unlink(missing_ok=True)
                log.warning("live_fetcher.stream_error", url=url, error=str(e))
                return None

        if written < 200:
            Path(tmp.name).unlink(missing_ok=True)
            return None

        ok, reason = is_real_document_file(tmp.name)
        if not ok:
            log.debug("live_fetcher.rejected", url=url, reason=reason)
            Path(tmp.name).unlink(missing_ok=True)
            return None

        log.info("live_fetcher.downloaded", url=url, bytes=written, suffix=suffix)
        return tmp.name

    except requests.RequestException as e:
        log.warning("live_fetcher.request_error", url=url, error=str(e))
        return None


def _extract_doc_links(html: str, base_url: str) -> list[str]:
    """Extract direct document links from HTML using BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin, urlsplit
    except ImportError:
        return []

    DOC_EXTS = {".pdf", ".zip", ".docx", ".doc", ".xlsx", ".xls", ".rar", ".7z", ".odt"}
    DOC_KEYWORDS = [
        "download", "unterlag", "dokument", "vergabe", "ausschreibung",
        "zip", "herunterladen", "datei", "attachment",
    ]

    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    seen: set[str] = set()

    for tag in soup.find_all("a", href=True):
        href = str(tag.get("href", ""))
        if not href or href.startswith("#") or href.startswith("javascript"):
            continue

        full = urljoin(base_url, href)
        if full in seen:
            continue

        path_lower = urlsplit(full).path.lower()
        text_lower = (tag.get_text() or "").lower()

        # Direct document extension
        if any(path_lower.endswith(ext) for ext in DOC_EXTS):
            seen.add(full)
            links.append(full)
            continue

        # Download keyword in href or text
        if any(kw in href.lower() or kw in text_lower for kw in DOC_KEYWORDS):
            seen.add(full)
            links.append(full)

    return links
