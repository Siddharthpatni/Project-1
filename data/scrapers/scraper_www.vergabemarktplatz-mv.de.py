import os, re, requests, hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import sync_playwright
import html

DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xml", ".xls", ".xlsx",
            ".ods", ".odt", ".gaeb", ".x81", ".x83", ".ppt", ".pptx", ".txt", ".rar", ".7z"}

def _download_file(session: requests.Session, url: str, output_dir: str, saved_files: list) -> None:
    try:
        with session.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "").lower()
            
            # Determine filename from Content-Disposition header
            filename = None
            if "content-disposition" in r.headers:
                cd = r.headers["content-disposition"]
                fname_match = re.search(r"filename\*?=['\"]?(?:UTF-8''|)([^\;\s]+)", cd, re.IGNORECASE)
                if fname_match:
                    filename = requests.utils.unquote(fname_match.group(1))

            if not filename:
                # Fallback: create a filename from URL hash and Content-Type extension
                # or a generic name if Content-Type is not helpful
                url_path = urlparse(url).path
                base_name = os.path.basename(url_path)
                
                # Check for known extensions in the path
                ext_match = re.search(r"\.([a-z0-9]+)$", base_name, re.IGNORECASE)
                if ext_match and f".{ext_match.group(1).lower()}" in DOC_EXTS:
                    filename = base_name
                else: # Try to infer from content-type
                    if "pdf" in content_type:
                        filename = base_name if base_name else f"{hashlib.md5(url.encode()).hexdigest()}.pdf"
                    elif "zip" in content_type:
                        filename = base_name if base_name else f"{hashlib.md5(url.encode()).hexdigest()}.zip"
                    elif "excel" in content_type or "spreadsheetml" in content_type:
                        filename = base_name if base_name else f"{hashlib.md5(url.encode()).hexdigest()}.xlsx"
                    elif "word" in content_type or "document" in content_type:
                        filename = base_name if base_name else f"{hashlib.md5(url.encode()).hexdigest()}.docx"
                    elif "xml" in content_type:
                        filename = base_name if base_name else f"{hashlib.md5(url.encode()).hexdigest()}.xml"
                    elif "text" in content_type:
                        filename = base_name if base_name else f"{hashlib.md5(url.encode()).hexdigest()}.txt"
                    elif "octet-stream" in content_type or "application/x-zip-compressed" in content_type:
                        # Best guess, might be ZIP or something else. Play it safe with .bin or .zip
                        if "zip" in url.lower() or "archive" in url.lower():
                            filename = base_name if base_name else f"{hashlib.md5(url.encode()).hexdigest()}.zip"
                        else:
                            filename = base_name if base_name else f"{hashlib.md5(url.encode()).hexdigest()}.bin"
                    else:
                        filename = base_name if base_name else f"{hashlib.md5(url.encode()).hexdigest()}.unknown"

            filepath = os.path.join(output_dir, filename)
            # Ensure unique filename to prevent overwriting
            counter = 1
            original_filepath = filepath
            while os.path.exists(filepath):
                name, ext = os.path.splitext(original_filepath)
                filepath = f"{name}_{counter}{ext}"
                counter += 1

            with open(filepath, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            saved_files.append(str(Path(filepath).resolve()))
    except requests.exceptions.RequestException as e:
        print(f"Error downloading {url}: {e}")
    except IOError as e:
        print(f"Error saving file {filename}: {e}")


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    session = requests.Session()
    base_url = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(url))

    try:
        # --- DTVP (VMPSatellite/Satellite family) Check ---
        m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
        if m and ("/Satellite/" in url or "/VMPSatellite/" in url):
            project_id = m.group(1)
            prefix = "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"
            parts = urlparse(url)
            zip_url = f"{parts.scheme}://{parts.netloc}/{prefix}/public/company/project/{project_id}/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
            _download_file(session, zip_url, output_dir, saved)
            if saved: # If ZIP found and downloaded, we are done
                return {"downloaded_files": saved}

        # --- NetServer family ---
        if "/NetServer/" in url:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            tender_oid = None
            if 'TenderOID' in query_params:
                tender_oid = query_params['TenderOID'][0]
            elif 'TWOID' in query_params: # Some NetServer URLs use TWOID initially
                # The direct detail page will have TenderOID
                page_content = session.get(url, timeout=10).text
                match = re.search(r'name="TOID" value="([^"]+)"', page_content)
                if match:
                    tender_oid = match.group(1)
                else: # Also try finding the link to the actual TenderingProcedureDetails page
                    link_match = re.search(r'href="(TenderingProcedureDetails\?function=_Details&amp;TenderOID=[^"]+)"', page_content)
                    if link_match:
                        detail_link = html.unescape(urljoin(base_url, link_match.group(1)))
                        parsed_detail_url = urlparse(detail_link)
                        detail_query_params = parse_qs(parsed_detail_url.query)
                        if 'TenderOID' in detail_query_params:
                            tender_oid = detail_query_params['TenderOID'][0]

            if tender_oid:
                netserver_zip_url_candidate = urljoin(base_url, f"/NetServer/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={tender_oid}")
                _download_file(session, netserver_zip_url_candidate, output_dir, saved)
                if saved: # If ZIP found and downloaded, we are done
                    return {"downloaded_files": saved}

            # If no ZIP, try to find individual files
            response = session.get(url, timeout=10)
            response.raise_for_status()
            
            # Use Playwright for broader link search if direct methods fail
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)

                # Search for "Unterlagen zur Ansicht herunterladen" first, which might lead to documents
                view_docs_link = page.locator('a:has-text("Unterlagen zur Ansicht herunterladen")')
                if view_docs_link.is_visible():
                    view_docs_url = view_docs_link.get_attribute('href')
                    if view_docs_url:
                        view_docs_full_url = urljoin(base_url, view_docs_url)
                        page.goto(view_docs_full_url, wait_until="domcontentloaded")
                        # Now look for individual downloads on this new page
                        links = page.locator('a[href*="function=_DownloadDocument"]').all()
                        for link_elem in links:
                            file_url = link_elem.get_attribute('href')
                            if file_url:
                                full_file_url = urljoin(base_url, file_url)
                                _download_file(session, full_file_url, output_dir, saved)
                else: # Fallback to looking at all links directly on the current page if previous step didn't work
                    for link_elem in page.locator('a').all():
                        href = link_elem.get_attribute('href')
                        if href and 'function=_DownloadDocument' in href:
                            full_file_url = urljoin(base_url, href)
                            _download_file(session, full_file_url, output_dir, saved)
                browser.close()
            return {"downloaded_files": saved}
        
        # --- evergabe.de ---
        if "evergabe.de" in url and "unterlagen" not in url:
            tender_id_match = re.search(r'/([^/]+)$', urlparse(url).path)
            if tender_id_match:
                tender_id = tender_id_match.group(1)
                docs_url = f"https://www.evergabe.de/unterlagen/{tender_id}"
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    ctx = browser.new_context(
                        accept_downloads=True, locale="de-DE",
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                    )
                    page = ctx.new_page()
                    page.goto(docs_url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(5000) # Wait for page to render fully

                    for link_elem in page.locator('a:has-text("Datei herunterladen")').all():
                        href = link_elem.get_attribute('href')
                        if href:
                            full_file_url = urljoin(docs_url, href)
                            _download_file(session, full_file_url, output_dir, saved)
                    browser.close()
                return {"downloaded_files": saved}

        # --- eVergabe 4.9 / Cosinex family ---
        if any(domain in url for domain in ["vergabe.nrw.de", "vergabemarktplatz.brandenburg.de",
                                            "vergabe.muenchen.de", "bieterportal.noncd.db.de",
                                            "evergabe.bayern.de", "ausschreibungen.kfw.de"]) or \
           "eVergabe" in url or "Angular" in requests.get(url, timeout=10).text: # Simple heuristic for Angular
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.set_default_timeout(20000) # 20 second timeout for page operations
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(7000) # Wait for angular to render

                # Try to click "Teilnehmen" or "Vergabeunterlagen" tab if available
                try:
                    tab = page.locator('button:has-text("Alle herunterladen")')
                    if tab.count() == 0:
                        tab = page.locator('li a:has-text("Vergabeunterlagen")').first
                    if tab.count() == 0:
                        tab = page.locator('li a:has-text("Teilnehmen")').first

                    if tab.is_visible():
                        tab.click()
                        page.wait_for_timeout(2000) # Wait after click for new content
                except Exception:
                    pass # Tab might not exist or already on the right tab

                download_button = page.locator('button:has-text("Alle herunterladen")')
                if download_button.is_visible():
                    with page.expect_download() as dl_info:
                        download_button.scroll_into_view_if_needed()
                        download_button.click()
                    download = dl_info.value
                    download_path = os.path.join(output_dir, download.suggested_filename)
                    download.save_as(download_path)
                    saved.append(str(Path(download_path).resolve()))
                browser.close()
            if saved:
                return {"downloaded_files": saved}

        # --- evergabe-online.de ---
        if "evergabe-online.de" in url:
            response = session.get(url, timeout=10)
            response.raise_for_status()
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                if 'zipDownloadButton' in a_tag['href']:
                    zip_url = urljoin(base_url, html.unescape(a_tag['href']))
                    if "archivedProcedures.html" not in zip_url and "login.html" not in zip_url:
                        _download_file(session, zip_url, output_dir, saved)
                        return {"downloaded_files": saved} # Prioritize zip

        # --- subreport.de and subreport-elvis.de ---
        if "subreport.de" in url or "subreport-elvis.de" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.set_default_timeout(20000)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(5000) # Wait for page to render

                # Click "anzeigen" button to reveal documents
                anzeigen_button = page.locator('button:has-text("anzeigen")')
                if anzeigen_button.is_visible():
                    anzeigen_button.click()
                    page.wait_for_timeout(5000) # Wait for content to load

                # Find the ZIP-Paket download button
                zip_download_button = page.locator('tr:has-text("ZIP-Paket") >> button:has-text("download")').last
                if not zip_download_button.is_visible():
                    zip_download_button = page.locator('tr:has-text("Alle Dokumente") >> button:has-text("download")').last

                if zip_download_button.is_visible():
                    with page.expect_download() as dl_info:
                        zip_download_button.click()
                    download = dl_info.value
                    download_path = os.path.join(output_dir, download.suggested_filename)
                    download.save_as(download_path)
                    saved.append(str(Path(download_path).resolve()))
                browser.close()
            if saved:
                return {"downloaded_files": saved}

        # --- deutsche-evergabe.de ---
        if "deutsche-evergabe.de" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.set_default_timeout(20000)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(5000)

                bek_summary = page.locator('a.BekSummary').first
                if bek_summary.is_visible():
                    bek_summary.click()
                    page.wait_for_timeout(5000) # Wait for modal

                    current_url = page.url
                    uuid_match = re.search(r'/dashboards/dashboard_off/([a-f0-9-]+)', current_url)
                    if uuid_match:
                        uuid = uuid_match.group(1)
                        file_data = page.evaluate('''(uuid_param) => {
                            return new Promise((resolve, reject) => {
                                fetch("/Verfahren/dxVUFilesForSupplier/" + uuid_param)
                                    .then(r => r.json())
                                    .then(data => resolve(data))
                                    .catch(err => reject(err));
                            });
                        }''', uuid)
                        
                        for item in file_data:
                            doc_id_str = item.get("DokIDStr")
                            file_name = item.get("Filename")
                            if doc_id_str and file_name:
                                doc_url = f"https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id={doc_id_str}"
                                _download_file(session, doc_url, output_dir, saved)
                browser.close()
            if saved:
                return {"downloaded_files": saved}
            
        # --- bi-medien.de ---
        if "bi-medien.de" in url or "deutsches-ausschreibungsblatt.de" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.set_default_timeout(20000)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay

                vergabeunterlagen_link = page.locator('a:has-text("Vergabeunterlagen")').first
                if vergabeunterlagen_link.is_visible():
                    with ctx.expect_page() as new_page_info:
                        vergabeunterlagen_link.click()
                    new_page = new_page_info.value
                    new_page.wait_for_load_state("domcontentloaded")
                    new_page.wait_for_timeout(3000)
                    new_page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay on new page

                    zip_link = new_page.locator('a:has-text("Unterlagen als ZIP-Datei")').first
                    if zip_link.is_visible():
                        href = zip_link.get_attribute('href')
                        if href:
                            full_zip_url = urljoin(new_page.url, href)
                            _download_file(session, full_zip_url, output_dir, saved)
                    new_page.close()
                browser.close()
            if saved:
                return {"downloaded_files": saved}
            
        # --- vergabe24.de and bund.vergabe24.de ---
        if "vergabe24.de" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.set_default_timeout(30000) # Increased timeout for multi-step navigation
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)

                # Check for redirect to NetServer
                if page.url and "/NetServer/" in page.url and page.url != url:
                    # If redirected to NetServer, call NetServer logic.
                    browser.close() # Close current browser
                    return scrape(page.url, output_dir)

                # Step 1: Click "Vergabeunterlagen anfordern"
                anfordern_button = page.locator('td a:has-text("Vergabeunterlagen anfordern")').first
                if anfordern_button.is_visible():
                    anfordern_button.click()
                    page.wait_for_timeout(2000)

                    # Step 2: Click "Unterlagen zur Ansicht herunterladen" in popup
                    ansicht_download_button = page.locator('td button:has-text("Unterlagen zur Ansicht herunterladen")').first
                    if ansicht_download_button.is_visible():
                        ansicht_download_button.click()
                        page.wait_for_timeout(2000)
                        
                        # Step 3: Click "Weiter"
                        weiter_button = page.locator('button:has-text("Weiter")').first
                        if weiter_button.is_visible():
                            weiter_button.click()
                            page.wait_for_timeout(2000)

                            # Step 4: Final page, click "Vergabeunterlagen als ZIP-Datei herunterladen"
                            zip_download_button = page.locator('button:has-text("Vergabeunterlagen als ZIP-Datei herunterladen")')
                            if zip_download_button.is_visible():
                                with page.expect_download() as dl_info:
                                    zip_download_button.click()
                                download = dl_info.value
                                download_path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(download_path)
                                saved.append(str(Path(download_path).resolve()))
                browser.close()
            if saved:
                return {"downloaded_files": saved}
            
        # --- SharePoint (:f: folder sharing links) ---
        if ".sharepoint.com/:f:" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.set_default_timeout(30000)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(8000) # Wait for React/Fluent UI to render

                download_button = page.locator('button[name="Download"], [data-automationid="downloadCommand"]').first
                if download_button.is_visible():
                    with page.expect_download() as dl_info:
                        download_button.click()
                    download = dl_info.value
                    download_path = os.path.join(output_dir, download.suggested_filename)
                    download.save_as(download_path)
                    saved.append(str(Path(download_path).resolve()))
                browser.close()
            if saved:
                return {"downloaded_files": saved}

        # --- Ariba (eu.mu.ariba.com) ---
        if "eu.mu.ariba.com" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.set_default_timeout(20000)
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(7000) # Wait for rendering

                download_all_button = page.locator('button:has-text("Download All"), button:has-text("Alle herunterladen")').first
                if download_all_button.is_visible():
                    download_all_button.scroll_into_view_if_needed()
                    with page.expect_download() as dl_info:
                        download_all_button.click()
                    download = dl_info.value
                    download_path = os.path.join(output_dir, download.suggested_filename)
                    download.save_as(download_path)
                    saved.append(str(Path(download_path).resolve()))
                browser.close()
            if saved:
                return {"downloaded_files": saved}

        # --- General Fallback for "Download All" / ZIP links via requests ---
        # If no platform-specific logic caught it, try generic ZIP/download-all
        response = session.get(url, timeout=10)
        response.raise_for_status()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')

        # Priority 1: href ends with .zip or contains downloadall etc.
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].lower()
            if href.endswith('.zip') or \
               'downloadall' in href or 'alleherunterladen' in href or \
               'alle-dokumente' in href or 'archive' in href:
                full_zip_url = urljoin(base_url, a_tag['href'])
                _download_file(session, full_zip_url, output_dir, saved)
                return {"downloaded_files": saved}

        # Priority 2: Visible text contains "alle herunterladen" etc.
        for a_tag in soup.find_all(['a', 'button']):
            text = a_tag.get_text(strip=True).lower()
            if any(phrase in text for phrase in [
                "alle herunterladen", "alle dokumente", "alle als zip", "alles herunterladen",
                "download all", "download zip", "zip herunterladen", "unterlagen herunterladen",
                "alle unterlagen", "gesamtpaket", "vergabeunterlagen herunterladen"
            ]):
                href = a_tag.get('href')
                if href:
                    full_link_url = urljoin(base_url, href)
                    _download_file(session, full_link_url, output_dir, saved)
                    return {"downloaded_files": saved}
                # Check for onclick that constructs ZIP download URL
                onclick = a_tag.get('onclick')
                if onclick and ("download" in onclick.lower() or "zip" in onclick.lower()):
                    # This is highly specific and might need custom JS parsing.
                    # For now, we'll skip complex onclick handling as it's hard to generalize for a fallback.
                    pass 

        # If no "download all" option, download individual files
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            parsed_href = urlparse(href)
            path_lower = parsed_href.path.lower()
            
            # Skip common non-document extensions or functional links
            if any(path_lower.endswith(ext) for ext in DOC_EXTS):
                # Heuristics to ignore navigation/login/external links
                if not any(keyword in href for keyword in ['login', 'register', 'javascript:', 'mailto:', 'tel:', 'http', 'https']):
                    full_file_url = urljoin(base_url, href)
                    # Basic check to avoid re-downloading the main page or similar
                    if urlparse(full_file_url).path != urlparse(url).path:
                        _download_file(session, full_file_url, output_dir, saved)

    except Exception as e:
        print(f"An error occurred during scraping: {e}")
    finally:
        session.close()

    return {"downloaded_files": saved}