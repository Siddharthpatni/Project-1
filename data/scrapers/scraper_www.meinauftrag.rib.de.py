"""
Phase 0 Manual Scraper — V1 Reference Implementation.
Ported from https://github.com/Siddharthpatni/Vergabepilot-v1.git

This scraper handles complex German procurement portals with:
- URL recovery (Vergabe24/Tender24)
- Cookie banner dismissal
- Multi-pass document identification and downloading
"""

import os
import re
import time
import requests
import hashlib
from pathlib import Path
from urllib.parse import urlparse, urljoin, quote, quote_plus, unquote
from playwright.sync_api import sync_playwright

# ---------- Configuration & Keywords ----------

DOCUMENT_EXTENSIONS = {
    ".pdf", ".zip", ".doc", ".docx", ".xls", ".xlsx", ".rar", ".7z",
    ".odt", ".ods", ".p7s", ".gaeb", ".x81", ".x83", ".d83", ".d84",
}

DOC_TEXT_KEYWORDS = [
    "unterlag", "leistungsverzeichnis", "leistungsbeschreibung",
    "ausschreibung", "vergabeunterlag", "angebotsunterlag",
    "gaeb", "download", "dokument", "alle dokumente",
]

DOC_SKIP_TEXT = ["agb", "datenschutz", "impressum", "login", "registrierung"]

NETSERVER_URL_TEMPLATES = [
    "https://www.vergabe24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
    "https://www.vergabe24.de/NetServer/PublicationControllerServlet?function=Detail&TWOID={tid}&PublicationType=0",
    "https://www.tender24.de/NetServer/TenderingProcedureDetails?function=_Details&TenderOID={tid}",
]

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9",
}

# ---------- URL Recovery Logic ----------

def extract_tender_id(url):
    match = re.search(r"(54321-(?:Tender|PublishingProcess)-[a-f0-9][a-f0-9\-]+)", url, re.IGNORECASE)
    return match.group(1) if match else None

def recover_url(original_url):
    tid = extract_tender_id(original_url)
    if not tid:
        return original_url
    
    for template in NETSERVER_URL_TEMPLATES:
        url = template.format(tid=tid)
        try:
            resp = requests.get(url, headers=BROWSER_HEADERS, timeout=5)
            if resp.status_code == 200 and len(resp.text) > 1000:
                return url
        except:
            continue
    return original_url

# ---------- Helper Functions ----------

def dismiss_cookies(page):
    selectors = [
        "xpath=//button[contains(.,'Akzeptieren')]",
        "xpath=//button[contains(.,'Alle akzeptieren')]",
        "xpath=//button[contains(.,'Annehmen')]",
        "text=Einverstanden",
    ]
    for sel in selectors:
        try:
            if page.is_visible(sel, timeout=500):
                page.click(sel)
                return True
        except:
            pass
    return False

def score_link(href, text, domain):
    low_href = href.lower()
    low_text = (text or "").lower()
    
    if any(k in low_href for k in ["/agb", "/login"]): return 0
    if any(k in low_text for k in DOC_SKIP_TEXT): return 0
    
    score = 0
    ext = Path(urlparse(href).path).suffix.lower()
    if ext in DOCUMENT_EXTENSIONS: score += 1
    if any(k in low_text for k in DOC_TEXT_KEYWORDS): score += 2
    
    return score

# ---------- Core Scraper ----------

def scrape(url: str, output_dir: str) -> list[str]:
    """
    Main entry point for the manual scraper.
    """
    downloaded_paths = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, user_agent=BROWSER_HEADERS["User-Agent"])
        page = context.new_page()
        
        # 1. Recovery & Initial Load
        final_url = recover_url(url)
        try:
            page.goto(final_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            dismiss_cookies(page)
        except Exception as e:
            browser.close()
            return []

        # 2. Identify candidate links
        page_domain = urlparse(page.url).netloc.lower()
        links = page.query_selector_all("a[href]")
        candidates = []
        for link in links:
            try:
                href = link.get_attribute("href")
                text = link.inner_text()
                if not href or href.startswith("#"): continue
                
                full_url = urljoin(page.url, href)
                score = score_link(full_url, text, page_domain)
                if score > 0:
                    candidates.append((full_url, score, link))
            except:
                continue

        # Sort by score (best first)
        candidates.sort(key=lambda x: -x[1])

        # 3. Download Strategy
        content_hashes = set()
        for i, (doc_url, score, element) in enumerate(candidates):
            if i >= 10: break # Safety cap
            
            try:
                # Use Playwright's download handler
                with page.expect_download(timeout=10000) as download_info:
                    element.click(force=True)
                
                download = download_info.value
                suggested_name = download.suggested_filename
                
                # Deduplicate by name and extension
                ext = Path(suggested_name).suffix.lower()
                if not ext: ext = ".pdf"
                
                save_path = os.path.join(output_dir, suggested_name)
                download.save_as(save_path)
                downloaded_paths.append(save_path)
                
            except Exception:
                # Fallback to direct requests if click fails
                try:
                    r = requests.get(doc_url, headers=BROWSER_HEADERS, timeout=10)
                    if r.status_code != 200 or len(r.content) < 100:
                        continue

                    content_type = r.headers.get("content-type", "").lower()
                    # Skip HTML responses — those are web pages, not documents
                    if "html" in content_type:
                        continue
                    if b"<html" in r.content[:500].lower():
                        continue

                    h = hashlib.md5(r.content[:4096]).hexdigest()
                    if h in content_hashes:
                        continue
                    content_hashes.add(h)

                    # Determine extension from content-type or magic bytes
                    if "zip" in content_type or r.content.startswith(b"PK"):
                        ext = ".zip"
                    elif "xml" in content_type:
                        ext = ".xml"
                    elif r.content.startswith(b"%PDF"):
                        ext = ".pdf"
                    else:
                        url_ext = Path(urlparse(doc_url).path).suffix.lower()
                        ext = url_ext if url_ext in DOCUMENT_EXTENSIONS else ".bin"

                    name = f"doc_{i}_{h[:6]}{ext}"
                    save_path = os.path.join(output_dir, name)
                    with open(save_path, "wb") as f:
                        f.write(r.content)
                    downloaded_paths.append(save_path)
                except Exception:
                    continue

        browser.close()
    
    return downloaded_paths

if __name__ == "__main__":
    # Test locally
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.evergabe-online.de/tenderdetails.html?id=example1"
    out = "./test_downloads"
    os.makedirs(out, exist_ok=True)
    files = scrape(test_url, out)
    print(f"Downloaded: {files}")
