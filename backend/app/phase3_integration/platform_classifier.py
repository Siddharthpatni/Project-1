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
# URL normalization  (run before classification / cascade)
# ---------------------------------------------------------------------------

def normalize_url(url: str) -> str:
    """Rewrite known *login-entrance* / landing URLs to the public tender page
    that actually exposes documents.

    Some source URLs (e.g. exported lists) point at a portal's login entrance or
    a redirect stub rather than the public page that serves the documents.
    Scraping the entrance yields nothing; rewriting to the public page lets the
    cascade (and the CUA) start where the documents actually are.

    Handled today:
      * EU-Supply CTM:  /app/rfq/rwlentrance_s.asp?PID=<id>   (login entrance)
                     →  /ctm/Supplier/PublicPurchase/<id>/0/0  (public page)
    """
    try:
        parts = urlsplit(url)
    except Exception:  # noqa: BLE001
        return url
    host = (parts.netloc or "").lower()

    # EU-Supply CTM family (eu.eu-supply.com, www.eu-supply.com, <tenant>.eu-supply.com)
    if "eu-supply.com" in host and "rwlentrance" in parts.path.lower():
        m = re.search(r"[?&]PID=(\d+)", url, re.IGNORECASE)
        if m:
            return f"{parts.scheme}://{parts.netloc}/ctm/Supplier/PublicPurchase/{m.group(1)}/0/0"

    return url


# ---------------------------------------------------------------------------
# URL-level fingerprints  (checked before any HTTP request)
# ---------------------------------------------------------------------------

_URL_PATTERNS: dict[str, list[str]] = {
    "dtvp": [
        r"/Satellite/public/company/project/",
        r"/VMPSatellite/public/company/project/",
        r"/Satellite/notice/",
        r"/VMPSatellite/notice/",
        r"/Vergabe/notice/",          # blb.nrw and similar Satellite variants
        r"/Vergabe/public/company/project/",
    ],
    "netserver": [
        r"/NetServer/",
    ],
    # eVergabe 4.9 / Cosinex deeplink API — used by kfw.de, db.de, ehealth portals etc.
    # Path: /evergabe.bieter/api/supplier/external/deeplink/subproject/<uuid>
    #   or: /bieter/api/supplier/external/deeplink/subproject/<uuid>
    "evergabe_cosinex": [
        r"/evergabe\.bieter/api/supplier/external/deeplink/",
        r"/bieter/api/supplier/external/deeplink/",
        r"evergabe\.bieter",
        r"evergabe\.nrw",
        r"evergabe\.bayern",
        r"vergabemarktplatz\.brandenburg",
        r"vergabe\.muenchen",
    ],
    # e-VA Bieterportal — bundde?data=<base64> format used by dfg.e-va.eu etc.
    "e_va": [
        r"e-va\.eu",
        r"/bundde\?data=",
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
    "evergabe_cosinex": [
        "evergabe.bieter",
        "Alle herunterladen",
        "ng-version",   # Angular app marker
        "cosinex",
    ],
    "e_va": [
        "e-va.eu",
        "bieterportal",
        "bundde",
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
DETERMINISTIC_PLATFORMS = {"dtvp", "netserver"}


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
    Handles forms:
      /project/CXXX/de/...   (documents/overview URLs)
      /notice/CXXX            (notice listing URLs — the form used in CSVs)
    Also handles IDs that contain lowercase or hyphens (some portals use these).
    """
    m = re.search(r"/(?:project|notice)/([A-Z0-9a-z]+)(?:/|$)", url, re.IGNORECASE)
    return m.group(1) if m else None


def _dtvp_prefix(url: str) -> str:
    """
    Return the correct path prefix for this Satellite-family portal.
    Handles VMPSatellite (NRW-style), standard Satellite, and Vergabe variants.
    """
    if "/VMPSatellite/" in url:
        return "VMPSatellite"
    if "/Vergabe/" in url:
        return "Vergabe"
    return "Satellite"


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
    Works for Satellite, VMPSatellite (NRW), and Vergabe prefix variants,
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


def build_netserver_download_url(url: str) -> str | None:
    """
    Construct the _DownloadTenderDocuments URL for a NetServer portal.

    Handles two URL forms:
      1. TenderingProcedureDetails?function=_Details&TenderOID=54321-Tender-...
         → TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID=...
      2. PublicationControllerServlet?function=Detail&TWOID=54321-Tender-...
         → TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID=...
    """
    from urllib.parse import urlsplit, parse_qs

    parts   = urlsplit(url)
    params  = parse_qs(parts.query, keep_blank_values=True)
    base    = f"{parts.scheme}://{parts.netloc}"
    netpath = re.search(r"(/.*?/NetServer/)", parts.path, re.IGNORECASE)
    ns_base = f"{base}{netpath.group(1)}" if netpath else f"{base}/NetServer/"

    # Extract TenderOID — may be under TenderOID or TWOID key
    oid = (params.get("TenderOID") or params.get("TWOID") or [None])[0]
    if not oid:
        # Try to find a 54321-Tender-* pattern anywhere in the URL
        m = re.search(r"(54321-(?:Tender|PublishingProcess)-[a-f0-9\-]+)", url, re.IGNORECASE)
        oid = m.group(1) if m else None
    if not oid:
        return None

    return f"{ns_base}TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={oid}"


def build_netserver_fallback_urls(url: str) -> list[str]:
    """
    Additional NetServer download URL patterns to try when the primary
    _DownloadTenderDocuments endpoint returns an empty body (common on portals
    that gate document access by session, or use a different endpoint path).

    Tries in order:
      1. PublicationControllerServlet GetDocumentFile (some portals serve
         documents here without a session when the publication is public)
      2. _DownloadPublicationDocuments (alternative NetServer function name)
      3. _DownloadTenderDocuments with explicit DocumentType param
    """
    from urllib.parse import urlsplit, parse_qs

    parts  = urlsplit(url)
    params = parse_qs(parts.query, keep_blank_values=True)
    base   = f"{parts.scheme}://{parts.netloc}"
    netpath = re.search(r"(/.*?/NetServer/)", parts.path, re.IGNORECASE)
    ns_base = f"{base}{netpath.group(1)}" if netpath else f"{base}/NetServer/"

    oid = (params.get("TenderOID") or params.get("TWOID") or [None])[0]
    if not oid:
        m = re.search(r"(54321-(?:Tender|PublishingProcess)-[a-f0-9\-]+)", url, re.IGNORECASE)
        oid = m.group(1) if m else None
    if not oid:
        return []

    return [
        # Alternate NetServer function names
        f"{ns_base}TenderingProcedureDetails?function=_DownloadPublicationDocuments&TenderOID={oid}",
        f"{ns_base}PublicationControllerServlet?function=GetDocumentFile&TWOID={oid}",
        f"{ns_base}TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={oid}&DocumentType=0",
        f"{ns_base}TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={oid}&DocumentType=1",
    ]


def build_download_url(platform: str, url: str) -> str | None:
    """
    Dispatch to the right URL builder for the given deterministic platform.
    Returns None if the platform isn't deterministic or the URL doesn't
    fit the expected shape.
    """
    if platform == "dtvp":
        return build_dtvp_zip_url(url)
    if platform == "netserver":
        return build_netserver_download_url(url)
    return None
