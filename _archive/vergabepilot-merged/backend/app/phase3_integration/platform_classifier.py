"""
Platform fingerprinting (no LLM, no HTTP).

Identifies which procurement platform a URL belongs to using URL patterns
first, then optional HTML content as fallback. For known platforms with
deterministic URL templates (DTVP/Satellite/VMPSatellite family), this
module can directly construct the ZIP download URL without any HTTP
request or LLM call — that's the fast path of the cascade.

Adapted from the development branch's `classifier.py`, which has been
proven across 100+ German procurement domains with ~89% success rate
on its target dataset.

Used by `phase3_integration.pipeline` as the DETERMINISTIC strategy,
inserted between EXISTING (registry) and LLM_GENERATED.
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
        r"/Satellite/notice/",
        r"/VMPSatellite/notice/",
    ],
    "netserver": [
        r"/NetServer/",
    ],
    "evergabe_de": [
        r"www\.evergabe\.de",
    ],
    "evergabe_online": [
        r"evergabe-online\.de",
    ],
    "ted_eu": [
        r"ted\.europa\.eu",
        r"enotices\.ted\.europa\.eu",
    ],
    "negometrix": [
        r"negometrix\.com",
        r"negometrix\.nl",
    ],
    "mercell": [
        r"mercell\.com",
    ],
    "subreport": [
        r"subreport\.de",
        r"subreport-elvis\.de",
    ],
    "deutsche_evergabe": [
        r"deutsche-evergabe\.de",
        r"bieterzugang\.deutsche-evergabe\.de",
    ],
    "bi_medien": [
        r"bi-medien\.de",
        r"deutsches-ausschreibungsblatt\.de",
    ],
    "vergabe24": [
        r"vergabe24\.de",
    ],
    "sharepoint": [
        r"\.sharepoint\.com/:f:/",
    ],
    "ariba": [
        r"eu\.mu\.ariba\.com",
    ],
}

# ---------------------------------------------------------------------------
# HTML-level fingerprints  (fallback when URL is ambiguous)
# ---------------------------------------------------------------------------

_HTML_PATTERNS: dict[str, list[str]] = {
    "dtvp": [
        "VMPSatellite",
        "DTVP",
    ],
    "netserver": [
        "NetServer",
        "TenderingProcedureDetails",
    ],
    "ted_eu": [
        "TED Tenders Electronic Daily",
        "Publications Office of the EU",
    ],
    "subreport": [
        "subreport ELViS",
        "subreport-elvis",
    ],
    "evergabe_online": [
        "Wicket",
        "evergabe-online",
    ],
}

# Platforms that have a deterministic URL template — no LLM needed.
# For these, the platform classifier can construct the document/ZIP URL
# directly from URL components.
DETERMINISTIC_PLATFORMS = {"dtvp"}


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


def is_deterministic(platform: str) -> bool:
    """True if this platform has a known URL template."""
    return platform in DETERMINISTIC_PLATFORMS


# ---------------------------------------------------------------------------
# DTVP-specific URL builders (Satellite / VMPSatellite family)
# ---------------------------------------------------------------------------

def extract_project_id(url: str) -> str | None:
    """
    Extract DTVP-style project ID from URL path.
    Handles both forms:
      /project/CXXX/de/...   (documents/overview URLs)
      /notice/CXXX            (notice listing URLs — the form used in CSVs)
    """
    m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
    return m.group(1) if m else None


def _dtvp_prefix(url: str) -> str:
    """Return 'VMPSatellite' or 'Satellite' based on URL path."""
    return "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"


def build_dtvp_documents_url(url: str) -> str | None:
    """Return the /documents page URL for a DTVP project."""
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


def build_download_url(platform: str, url: str) -> str | None:
    """
    Dispatch to the right URL builder for the given deterministic platform.
    Returns None if the platform isn't deterministic or the URL doesn't
    fit the expected shape.
    """
    if platform == "dtvp":
        return build_dtvp_zip_url(url)
    return None
