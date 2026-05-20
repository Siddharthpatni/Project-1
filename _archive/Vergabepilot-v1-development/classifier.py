"""
classifier.py — Platform fingerprinting (no LLM, no HTTP).

Identifies which procurement platform a URL belongs to using
URL patterns first, then optional HTML content as fallback.

Usage:
    from classifier import classify_url, classify_html, DTVP_PLATFORMS
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# URL-level fingerprints  (checked before any HTTP request)
# ---------------------------------------------------------------------------

_URL_PATTERNS: dict[str, list[str]] = {
    "dtvp": [
        r"/Satellite/public/company/project/",
        r"/VMPSatellite/public/company/project/",
    ],
    "ted_eu": [
        r"ted\.europa\.eu",
        r"enotices\.ted\.europa\.eu",
    ],
    "negometrix": [
        r"negometrix\.com",
        r"negometrix\.nl",
    ],
    "doffin": [
        r"doffin\.no",
    ],
    "mercell": [
        r"mercell\.com",
    ],
    "bravosolution": [
        r"bravosolution\.com",
        r"jaggaer\.com",
    ],
    "ionwave": [
        r"ionwave\.net",
    ],
    "bonfire": [
        r"gobonfire\.com",
    ],
    "procontract": [
        r"procontract\.due-north\.com",
    ],
    "mytenders": [
        r"mytenders\.org",
    ],
    "publicpurchase": [
        r"publicpurchase\.com",
    ],
}

# ---------------------------------------------------------------------------
# HTML-level fingerprints  (fallback when URL is ambiguous)
# ---------------------------------------------------------------------------

_HTML_PATTERNS: dict[str, list[str]] = {
    "dtvp": [
        "VMPSatellite",
        "DTVP",
        # NOTE: "vergabeportal" and "Vergabeunterlagen" removed — too generic,
        # they appear on NetServer and other non-DTVP platforms causing misclassification.
    ],
    "ted_eu": [
        "TED Tenders Electronic Daily",
        "Publications Office of the EU",
    ],
    "negometrix": [
        "negometrix",
    ],
    "mercell": [
        "mercell",
    ],
    "bravosolution": [
        "BravoSolution",
        "JAGGAER",
    ],
    "bonfire": [
        "bonfire",
        "gobonfire",
    ],
    "procontract": [
        "ProContract",
        "due-north",
    ],
}

# Platforms that use DTVP-style ZIP URL template (same software, different host)
DTVP_PLATFORMS = {"dtvp"}


def classify_url(url: str) -> str:
    """Return platform name from URL alone, or 'unknown'."""
    for platform, patterns in _URL_PATTERNS.items():
        for p in patterns:
            if re.search(p, url, re.IGNORECASE):
                return platform
    return "unknown"


def classify_html(url: str, html: str) -> str:
    """
    Classify using HTML when URL classification returned 'unknown'.
    Falls back to classify_url first so callers can use this as a
    single entry point.
    """
    result = classify_url(url)
    if result != "unknown":
        return result

    html_lower = html.lower()
    for platform, patterns in _HTML_PATTERNS.items():
        for p in patterns:
            if p.lower() in html_lower:
                return platform

    return "unknown"


def extract_project_id(url: str) -> str | None:
    """
    Extract DTVP-style project ID from URL path.
    Handles both forms:
      /project/CXXX/de/...   (documents/overview URLs)
      /notice/CXXX            (notice listing URLs — the form used in the CSV)
    """
    m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
    return m.group(1) if m else None


def _dtvp_prefix(url: str) -> str:
    """Return 'VMPSatellite' or 'Satellite' based on URL path."""
    return "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"


def build_dtvp_documents_url(url: str) -> str | None:
    """
    Return the /documents page URL for a DTVP project.
    Works from both /notice/ID and /project/ID/... URLs.
    """
    parts = urlsplit(url)
    project_id = extract_project_id(url)
    if not project_id:
        return None
    prefix = _dtvp_prefix(url)
    return (
        f"{parts.scheme}://{parts.netloc}"
        f"/{prefix}/public/company/project/{project_id}/de/documents"
    )


def build_dtvp_zip_url(url: str) -> str | None:
    """
    Construct the ZIP URL for a DTVP-family project URL using the known template.
    Works for both Satellite (BW) and VMPSatellite (NRW) prefixes,
    and from both /notice/ID and /project/ID/... URL forms.
    """
    parts = urlsplit(url)
    project_id = extract_project_id(url)
    if not project_id:
        return None
    prefix = _dtvp_prefix(url)
    return (
        f"{parts.scheme}://{parts.netloc}"
        f"/{prefix}/public/company/project/{project_id}"
        f"/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
    )
