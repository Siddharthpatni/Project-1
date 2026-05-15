"""
Document validator — closes the "HTML saved as document" bug.

The cascade pipeline (Phase 3) and the Phase-1 executor both need to
distinguish real tender documents (PDF, ZIP, DOCX, …) from HTML error
pages, login redirects, and other web junk that scrapers accidentally
download.

This module provides two validators:

  is_document_url(url)       — pre-flight check on a URL before downloading.
                                Ported from Vergabepilot-v1-development/pipeline.py
                                lines 81–145.

  is_real_document_file(path) — post-download check on a local file by
                                 inspecting its extension, magic bytes,
                                 and first-KB content.  This is the new
                                 piece that was missing from the backend.

Both functions use only stdlib — no external dependencies.
"""
from __future__ import annotations

import os
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# 1. URL-level validator (ported from dev-branch pipeline.py L81-145)
# ---------------------------------------------------------------------------

def is_document_url(url: str, timeout: int = 10) -> bool:
    """Trust download-style URLs by pattern; HEAD-check the rest.

    Returns True if the URL likely points to a real file download,
    False if it clearly points to an HTML page.  When in doubt (e.g.
    the server is unreachable), returns True so we don't silently
    drop valid URLs behind a firewall.
    """
    # URLs with known download-function patterns — trust them
    download_patterns = [
        r"_DownloadTenderDocuments",
        r"_DownloadDocument",
        r"_DownloadAll",
        r"function=.*[Dd]ownload",
        r"DownloadTenderFiles\.ashx",
        r"DirectDocload",
    ]
    for pat in download_patterns:
        if re.search(pat, url):
            return True

    # Wicket-based download endpoints (evergabe-online.de) — trust them
    if "zipDownloadButton" in url or "downloadAllButton" in url:
        return True

    # URLs ending in known HTML extensions — reject them
    # NOTE: .php/.asp/.aspx are dynamic and may serve files, so don't reject
    path_lower = urlsplit(url).path.lower()
    html_exts = (".html", ".htm", ".xhtml")
    if any(path_lower.endswith(ext) for ext in html_exts):
        return False

    # URLs ending in known file extensions — trust them
    file_exts = (
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".rar", ".7z", ".txt", ".odt", ".ods", ".csv",
    )
    if any(path_lower.endswith(ext) for ext in file_exts):
        return True

    # For other URLs, do a HEAD check and verify Content-Type
    try:
        req = Request(url, method="HEAD", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
        })
        with urlopen(req, timeout=timeout) as r:
            if r.status >= 400:
                return False
            ct = (r.headers.get("Content-Type") or "").lower()
            # Reject if the response is clearly HTML
            if "text/html" in ct or "application/xhtml" in ct:
                return False
            # Accept if Content-Type indicates a file
            if any(t in ct for t in ("application/", "octet-stream", "pdf", "zip",
                                     "msword", "spreadsheet", "presentation")):
                return True
            # Accept if Content-Disposition indicates a download
            cd = r.headers.get("Content-Disposition") or ""
            if "attachment" in cd.lower() or "filename" in cd.lower():
                return True
            # Unknown content type — accept cautiously
            return True
    except Exception:
        # Can't reach URL — still return True so we don't silently drop
        # valid URLs that just happen to be behind a firewall
        return True


# ---------------------------------------------------------------------------
# 2. Local-file validator (NEW — this is the missing piece)
# ---------------------------------------------------------------------------

# Known good document extensions (lower-cased, with dot)
_DOC_EXTENSIONS = frozenset({
    ".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".rar", ".7z", ".txt", ".odt", ".ods", ".csv", ".gaeb", ".x81", ".x83",
})

# Extensions that are always HTML
_HTML_EXTENSIONS = frozenset({".html", ".htm", ".xhtml"})

# HTML markers to look for in the first 1024 bytes (lowercased)
_HTML_MARKERS = [
    "<!doctype html",
    "<html",
    "<head>",
    "<script",
]

# Login/error title patterns (matched inside <title>…</title>)
_BAD_TITLE_PATTERNS = [
    "login",
    "fehler",
    "error",
]


def is_real_document_file(path: str) -> tuple[bool, str]:
    """Validate a downloaded file by inspecting its bytes.

    Returns (is_document, reason) where *reason* is a short string
    like ``"pdf"``, ``"html_content"``, or ``"unknown_content"``.
    """
    # --- 1. existence / size ---
    try:
        size = os.path.getsize(path)
    except OSError:
        return False, "too_small"

    if size < 200:
        return False, "too_small"

    # --- 2. read header bytes ---
    with open(path, "rb") as f:
        header = f.read(4096)

    ext = os.path.splitext(path)[1].lower()

    # --- 3. extension-based HTML rejection ---
    if ext in _HTML_EXTENSIONS:
        return False, "html_extension"

    # --- 4. content-based HTML rejection (first 1024 bytes) ---
    text_sample = header[:1024].decode("latin-1").lower()

    for marker in _HTML_MARKERS:
        if marker in text_sample:
            return False, "html_content"

    # Check for login/error in <title> tags
    title_match = re.search(r"<title[^>]*>(.*?)</title>", text_sample, re.DOTALL)
    if title_match:
        title_text = title_match.group(1).lower().strip()
        for bad in _BAD_TITLE_PATTERNS:
            if bad in title_text:
                return False, "html_content"

    # --- 5. magic-byte checks ---
    if header[:5] == b"%PDF-":
        return True, "pdf"

    if header[:4] == b"PK\x03\x04":
        # Could be plain ZIP or OOXML (docx/xlsx/pptx)
        return True, "zip_or_ooxml"

    if header[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return True, "ms_office_ole"

    if header[:6] == b"7z\xbc\xaf\x27\x1c":
        return True, "7z"

    if header[:7] == b"Rar!\x1a\x07":
        return True, "rar"

    # --- 6. extension-based acceptance for text-ish files ---
    text_ish_exts = frozenset({".txt", ".csv", ".odt", ".ods", ".gaeb", ".x81", ".x83"})
    if ext in text_ish_exts:
        return True, "extension_text_ok"

    # Also accept known doc extensions that didn't match a magic number
    # (e.g. a .pdf with a weird preamble but correct extension)
    if ext in _DOC_EXTENSIONS:
        return True, "extension_text_ok"

    # --- 7. fallback: reject ---
    return False, "unknown_content"
