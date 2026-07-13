"""
beschaffungen.barmer.de — Barmer NetServer portal.

URL type: NETSERVER_AUTH (TenderingProcedureDetails?function=_Details)
This portal requires vendor authentication — public document download is not available.
The circuit breaker will trip after 3 auth failures and skip further attempts for 30 min.

If the portal ever exposes PublicationControllerServlet public pages, this scraper
will fall through to the generic NetServer publication handler.
"""
import os
import re
import requests
from pathlib import Path
from urllib.parse import urlsplit

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
MAX_BYTES = 200 * 1024 * 1024


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    downloaded = []

    # Extract TenderOID
    m = re.search(r"TenderOID=([^&]+)", url) or re.search(r"(54321-(?:Tender|PublishingProcess)-[a-f0-9\-]+)", url, re.IGNORECASE)
    oid = m.group(1) if m else None

    if not oid:
        return {"downloaded_files": [], "error": "login_required: no public download URL available"}

    parts = urlsplit(url)
    ns_path = re.search(r"(/.*?/NetServer/)", parts.path, re.IGNORECASE)
    ns_base = f"{parts.scheme}://{parts.netloc}{ns_path.group(1)}" if ns_path else f"{parts.scheme}://{parts.netloc}/NetServer/"

    # Try publication download endpoints (public)
    candidates = [
        f"{ns_base}PublicationControllerServlet?function=Detail&TWOID={oid}&PublicationType=0",
        f"{ns_base}TenderingProcedureDetails?function=_DownloadPublicationDocuments&TenderOID={oid}",
    ]

    session = requests.Session()
    session.headers["User-Agent"] = UA

    for dl_url in candidates:
        try:
            r = session.get(dl_url, stream=True, timeout=20, allow_redirects=True)
            if r.status_code >= 400:
                continue
            ct = r.headers.get("content-type", "").lower()
            if "html" in ct:
                continue
            name = Path(dl_url.split("?")[0]).name or "document.zip"
            dest = Path(output_dir) / name
            size = 0
            with open(dest, "wb") as f:
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        dest.unlink(missing_ok=True)
                        break
                    f.write(chunk)
            if dest.exists() and dest.stat().st_size > 0:
                downloaded.append(str(dest))
                return {"downloaded_files": downloaded}
        except Exception as e:
            print(f"[barmer] attempt failed: {e}")

    return {
        "downloaded_files": [],
        "error": "login_required: barmer.de requires vendor authentication for document access",
    }
