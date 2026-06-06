import os, re, requests, hashlib
import html
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright

DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xml", ".xls", ".xlsx",
            ".ods", ".odt", ".gaeb", ".x81", ".x83", ".ppt", ".pptx", ".rar", ".7z", ".txt"}

def download_file(session, url, output_dir, saved):
    try:
        if not url:
            return
        # Ensure the URL is absolute
        if not urlparse(url).scheme:
             # This is a placeholder, as the target URL is a direct download,
             # we probably won't hit this for the main `url` but for other links.
             # Need a base_url from the initial page if this comes up later.
            return

        print(f"Attempting to download: {url}")
        with session.get(url, stream=True, timeout=10) as r:
            r.raise_for_status()
            content_type = r.headers.get("Content-Type", "").lower()
            filename = None

            # Try to get filename from Content-Disposition header
            cd = r.headers.get("Content-Disposition")
            if cd:
                fname_match = re.search(r"filename\*?=['\"]?(?:UTF-\d['\"]*)?([^;\"']*)", cd, re.IGNORECASE)
                if fname_match:
                    filename = fname_match.group(1).encode('latin-1').decode('utf-8', errors='ignore')
            
            # If filename still not found, try to extract from URL
            if not filename:
                path = urlparse(url).path
                filename = os.path.basename(path)
                # If it's a generic download path, try to guess from content type + a hash
                if not filename or filename.startswith("download") or filename.startswith("get"):
                    if "pdf" in content_type:
                        filename = f"document_{hashlib.md5(url.encode()).hexdigest()}.pdf"
                    elif "zip" in content_type:
                        filename = f"archive_{hashlib.md5(url.encode()).hexdigest()}.zip"
                    elif "xml" in content_type:
                        filename = f"data_{hashlib.md5(url.encode()).hexdigest()}.xml"
                    elif "excel" in content_type or "spreadsheetml" in content_type:
                        filename = f"spreadsheet_{hashlib.md5(url.encode()).hexdigest()}.xlsx"
                    elif "word" in content_type or "documentml" in content_type:
                        filename = f"document_{hashlib.md5(url.encode()).hexdigest()}.docx"
                    elif "text" in content_type:
                        filename = f"text_{hashlib.md5(url.encode()).hexdigest()}.txt"
                    else: # Fallback to a generic name
                        filename = f"file_{hashlib.md5(url.encode()).hexdigest()}"

            # Ensure filename has a valid extension, add a generic one if missing
            if "." not in filename:
                if "pdf" in content_type:
                    filename += ".pdf"
                elif "zip" in content_type:
                    filename += ".zip"
                elif "xml" in content_type:
                    filename += ".xml"
                elif "excel" in content_type or "spreadsheetml" in content_type:
                    filename += ".xlsx"
                elif "word" in content_type or "documentml" in content_type:
                    filename += ".docx"
                elif "text" in content_type:
                    filename += ".txt"
                else:
                    filename += ".bin" # Generic binary if no better guess


            filepath = Path(output_dir) / filename
            
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            print(f"Downloaded: {filepath}")
            saved.append(str(filepath.resolve()))
    except requests.exceptions.RequestException as e:
        print(f"Error downloading {url}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred during download of {url}: {e}")


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.60 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    })

    try:
        # Check for DTVP family based on URL patterns
        # This needs to be checked early as it provides a direct ZIP download
        if re.search(r"/(?:VMPSatellite|Satellite)/", url, re.IGNORECASE):
            m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
            if m:
                project_id = m.group(1)
                prefix = "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"
                parts = urlparse(url)
                dtvp_zip_url = f"{parts.scheme}://{parts.netloc}/{prefix}/public/company/project/{project_id}/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
                download_file(session, dtvp_zip_url, output_dir, saved)
                if saved: # If successful, we're done
                    return {"downloaded_files": saved}
            else:
                print(f"DTVP URL matched, but project ID not found: {url}. Falling back to generic parsing.")

        # The given URL "https://www.acingov.pt/acingovprod/2/zonaPublica/zona_publica_c/donwloadProcedurePiece/MTA2OTEyNQ"
        # seems to be a direct download link.
        # The HTML provided is actually the content of a ZIP file, not an HTML page.
        # This implies it's a direct ZIP download URL.
        # The "Detected platform: unknown" is correct here, as it's not a known procurement portal type.
        # We should attempt to download this URL directly as a file.
        if urlparse(url).path.endswith('/donwloadProcedurePiece/MTA2OTEyNQ'):
            print(f"Detected direct document download URL: {url}. Attempting direct download.")
            download_file(session, url, output_dir, saved)
            if saved:
                return {"downloaded_files": saved}

        # If it wasn't a direct download and not DTVP, proceed with Playwright for other platforms
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                accept_downloads=True, locale="de-DE",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.60 Safari/537.36"
            )
            page = ctx.new_page()
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                base_url = page.url # Update base_url after potential redirects

                # --- Priority Rule 1 & 2: "Download All" / ZIP via href or text ---
                zip_link_found = False
                zip_keywords = ["downloadall", "alleherunterladen", "alle-dokumente", "archive", "alle herunterladen", "alle dokumente", "alle als zip", "alles herunterladen", "download all", "download zip", "zip herunterladen", "unterlagen herunterladen", "alle unterlagen", "gesamtpaket", "vergabeunterlagen herunterladen"]
                zip_selectors = [
                    f"a[href$='.zip'], a[href*='downloadall'], a[href*='alleherunterladen'], a[href*='alle-dokumente'], a[href*='archive']",
                ]
                for kw in zip_keywords:
                    zip_selectors.append(f'a:has-text("{kw}")')
                    zip_selectors.append(f'button:has-text("{kw}")')

                for selector in zip_selectors:
                    elements = page.locator(selector).all()
                    for el in elements:
                        if el.is_visible():
                            href = el.get_attribute("href")
                            text = el.text_content()
                            
                            # Check if it's a valid "download all" link (not logout, js:void, etc.)
                            if href and not any(k in href for k in ["logout", "login", "javascript:void(0)"]) \
                                and not any(k in text.lower() for k in ["login", "logout"]):
                                
                                # Handle Playwright download for clicks
                                try:
                                    with page.expect_download(timeout=15000) as download_info: # 15s timeout
                                        el.click(timeout=10000) # Click with 10s timeout
                                    download = download_info.value
                                    
                                    file_path = Path(output_dir) / download.suggested_filename
                                    download.save_as(str(file_path))
                                    saved.append(str(file_path.resolve()))
                                    print(f"Playwright downloaded ZIP: {file_path}")
                                    zip_link_found = True
                                    break
                                except Exception as dl_err:
                                    print(f"Playwright download for '{selector}' failed: {dl_err}. Trying direct download if href available.")
                                    if href:
                                        full_url = urljoin(base_url, href)
                                        download_file(session, full_url, output_dir, saved)
                                        if saved:
                                            zip_link_found = True
                                            break
                            if zip_link_found:
                                break
                    if zip_link_found:
                        break

                if zip_link_found and saved:
                    browser.close()
                    return {"downloaded_files": saved}

                # --- Platform-specific handling if no general ZIP found ---

                # NetServer Family (vergabe.autobahn.de, tender24.de, sachsen-vergabe.de, vergabe.vmstart.de, vergabe.landbw.de)
                if "/NetServer/" in url or "vergabe.autobahn.de" in url or "tender24.de" in url or "sachsen-vergabe.de" in url or "vergabe.vmstart.de" in url or "vergabe.landbw.de" in url:
                    tender_oid_match = re.search(r"[?&]TenderOID=([^&]+)", url)
                    if tender_oid_match:
                        tender_oid = tender_oid_match.group(1)
                        # Attempt to construct the "Download All Documents" URL
                        netserver_zip_url = f"{urljoin(base_url, '/NetServer/TenderingProcedureDetails')}?function=_DownloadTenderDocuments&TenderOID={tender_oid}"
                        
                        # Look for hidden fields for additional parameters
                        hidden_inputs = page.query_selector_all('input[type="hidden"]')
                        params = {'TenderOID': tender_oid}
                        for h_input in hidden_inputs:
                            name = h_input.get_attribute('name')
                            value = h_input.get_attribute('value')
                            if name and value and name in ["documentOID", "TenderAuthority", "TenderDate"]:
                                params[name] = value
                        
                        zip_url_parts = [f"function=_DownloadTenderDocuments"]
                        for k, v in params.items():
                            zip_url_parts.append(f"{k}={v}")
                        netserver_zip_url = f"{urljoin(base_url, '/NetServer/TenderingProcedureDetails')}?{'&'.join(zip_url_parts)}"
                        
                        download_file(session, netserver_zip_url, output_dir, saved)
                        if saved:
                            browser.close()
                            return {"downloaded_files": saved}
                    
                    # Fallback to individual NetServer files
                    for a_tag in page.locator('a[href*="function=_DownloadDocument"]').all():
                         href = a_tag.get_attribute('href')
                         if href:
                             full_url = urljoin(base_url, href)
                             download_file(session, full_url, output_dir, saved)
                    browser.close()
                    return {"downloaded_files": saved}

                # evergabe.de
                elif "evergabe.de" in url and not "evergabe-online.de" in url:
                    tender_id_match = re.search(r"(\d+)$", urlparse(url).path)
                    if tender_id_match:
                        tender_id = tender_id_match.group(1)
                        documents_url = f"https://www.evergabe.de/unterlagen/{tender_id}"
                        page.goto(documents_url, wait_until="networkidle", timeout=20000)
                        
                        for _ in range(3): # Retry navigation to documents page
                            current_url = page.url
                            if f"/unterlagen/{tender_id}" in current_url:
                                break
                            print(f"Redirected from documents URL. Current URL: {current_url}. Retrying...")
                            page.goto(documents_url, wait_until="networkidle", timeout=20000)
                            page.wait_for_timeout(2000) # Wait a bit before checking again

                        page.wait_for_selector('a:has-text("Datei herunterladen")', timeout=10000).wait_for_element_state("stable")
                        
                        links_to_check = page.locator('a:has-text("Datei herunterladen")').all()
                        
                        for link in links_to_check:
                            href = link.get_attribute("href")
                            if href and any(ext in href.lower() for ext in DOC_EXTS):
                                try:
                                    with page.expect_download(timeout=15000) as download_info:
                                        link.click(timeout=10000)
                                    download = download_info.value
                                    file_path = Path(output_dir) / download.suggested_filename
                                    download.save_as(str(file_path))
                                    saved.append(str(file_path.resolve()))
                                    print(f"Playwright downloaded: {file_path}")
                                    page.wait_for_timeout(5000) # Rate limit
                                except Exception as dl_err:
                                    print(f"Playwright download failed for {href}: {dl_err}. Trying requests.")
                                    full_url = urljoin(base_url, href)
                                    download_file(session, full_url, output_dir, saved)
                                    page.wait_for_timeout(5000) # Rate limit
                    browser.close()
                    return {"downloaded_files": saved}

                # eVergabe 4.9 / Cosinex family (Angular/JS heavy)
                elif "kfw.vergabe.nrw.de" in url or "vergabemarktplatz.brandenburg.de" in url or "vergabe.muenchen.de" in url or "bieterportal.noncd.db.de" in url or "evergabe.bayern.de" in url or "ausschreibungen.kfw.de" in url:
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(5000) # Wait for Angular to render

                    # Try to locate and click "Alle herunterladen"
                    try:
                        all_download_button = page.locator('button:has-text("Alle herunterladen")')
                        if all_download_button.is_visible():
                            all_download_button.scroll_into_view_if_needed(timeout=5000)
                            with page.expect_download(timeout=30000) as download_info:
                                all_download_button.click(timeout=15000)
                            download = download_info.value
                            file_path = Path(output_dir) / download.suggested_filename
                            download.save_as(str(file_path))
                            saved.append(str(file_path.resolve()))
                            print(f"Playwright downloaded 'Alle herunterladen': {file_path}")
                            browser.close()
                            return {"downloaded_files": saved}
                    except Exception as e:
                        print(f"Could not find or click 'Alle herunterladen' or download failed: {e}. Trying other tabs/links.")

                    # Try clicking "Teilnehmen" or "Vergabeunterlagen" tab if exists
                    try:
                        teilnehmen_tab = page.locator('text=/^Teilnehmen$/i')
                        if teilnehmen_tab.is_visible():
                            teilnehmen_tab.click(timeout=5000)
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(3000)
                            
                            all_download_button = page.locator('button:has-text("Alle herunterladen")')
                            if all_download_button.is_visible():
                                all_download_button.scroll_into_view_if_needed(timeout=5000)
                                with page.expect_download(timeout=30000) as download_info:
                                    all_download_button.click(timeout=15000)
                                download = download_info.value
                                file_path = Path(output_dir) / download.suggested_filename
                                download.save_as(str(file_path))
                                saved.append(str(file_path.resolve()))
                                print(f"Playwright downloaded 'Alle herunterladen' after 'Teilnehmen': {file_path}")
                                browser.close()
                                return {"downloaded_files": saved}
                    except Exception as e:
                            print(f"Could not find or click 'Teilnehmen' or download failed: {e}.")

                    # Fallback to individual links if no ZIP found after tab clicks
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        if href and any(ext in href.lower() for ext in DOC_EXTS):
                            full_url = urljoin(base_url, href)
                            file_name_from_href = os.path.basename(urlparse(full_url).path)
                            if file_name_from_href and not any(k in file_name_from_href.lower() for k in ["login", "logout"]):
                                try:
                                    with page.expect_download(timeout=15000) as download_info:
                                        a_tag.click(timeout=10000)
                                    download = download_info.value
                                    file_path = Path(output_dir) / download.suggested_filename
                                    download.save_as(str(file_path))
                                    saved.append(str(file_path.resolve()))
                                    print(f"Playwright downloaded individual file: {file_path}")
                                except Exception as dl_err:
                                    print(f"Playwright download failed for {full_url}: {dl_err}. Trying requests for individual link.")
                                    download_file(session, full_url, output_dir, saved)
                    browser.close()
                    return {"downloaded_files": saved}


                # evergabe-online.de (Apache Wicket)
                elif "evergabe-online.de" in url:
                    # Look for zipDownloadButton
                    wicket_zip_link = page.locator('a[href*="zipDownloadButton"]').get_attribute('href')
                    if wicket_zip_link:
                        unescaped_url = html.unescape(wicket_zip_link)
                        full_url = urljoin(base_url, unescaped_url)
                        download_file(session, full_url, output_dir, saved)
                        if saved:
                            browser.close()
                            return {"downloaded_files": saved}

                    # Fallback to individual files
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        if href and any(ext in href.lower() for ext in DOC_EXTS) and \
                           "archivedProcedures.html" not in href and "login.html" not in href:
                            full_url = urljoin(base_url, html.unescape(href))
                            download_file(session, full_url, output_dir, saved)
                    browser.close()
                    return {"downloaded_files": saved}

                # subreport.de and subreport-elvis.de
                elif "subreport.de" in url:
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(5000) # Wait for page to settle

                    # Click "anzeigen" to reveal document list
                    try:
                        anzeigen_button = page.locator('button:has-text("anzeigen")')
                        if anzeigen_button.is_visible():
                            anzeigen_button.click(timeout=5000)
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(5000) # Wait for docs to appear
                    except Exception as e:
                        print(f"Could not find or click 'anzeigen' button: {e}. Proceeding anyway.")
                    
                    # Find ZIP download
                    try:
                        zip_download_row = page.locator('tr:has-text("ZIP-Paket"), tr:has-text("Alle Dokumente")').last
                        if zip_download_row.is_visible():
                            download_button_in_row = zip_download_row.locator('button:has-text("download"), a:has-text("download")').first
                            if download_button_in_row.is_visible():
                                with page.expect_download(timeout=30000) as download_info:
                                    download_button_in_row.click(timeout=15000)
                                download = download_info.value
                                file_path = Path(output_dir) / download.suggested_filename
                                download.save_as(str(file_path))
                                saved.append(str(file_path.resolve()))
                                print(f"Playwright downloaded Subreport ZIP: {file_path}")
                                browser.close()
                                return {"downloaded_files": saved}
                    except Exception as e:
                        print(f"Could not find and download Subreport ZIP: {e}. Trying individual files.")

                    # Fallback to individual files
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        if href and any(ext in href.lower() for ext in DOC_EXTS):
                            full_url = urljoin(base_url, href)
                            try:
                                with page.expect_download(timeout=15000) as download_info:
                                    a_tag.click(timeout=10000)
                                download = download_info.value
                                file_path = Path(output_dir) / download.suggested_filename
                                download.save_as(str(file_path))
                                saved.append(str(file_path.resolve()))
                                print(f"Playwright downloaded individual Subreport file: {file_path}")
                            except Exception as dl_err:
                                print(f"Playwright download failed for {full_url}: {dl_err}. Trying requests for individual link.")
                                download_file(session, full_url, output_dir, saved)
                    browser.close()
                    return {"downloaded_files": saved}


                # deutsche-evergabe.de
                elif "deutsche-evergabe.de" in url or "bieterzugang.deutsche-evergabe.de" in url:
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(5000)

                    # Click a.BekSummary or similar to open modal
                    try:
                        bek_summary_link = page.locator('a.BekSummary').first
                        if bek_summary_link.is_visible():
                            bek_summary_link.click(timeout=5000)
                            page.wait_for_timeout(5000) # Wait for modal to load

                            current_mod_url = page.url
                            uuid_match = re.search(r"/dashboards/dashboard_off/([0-9a-fA-F-]+)", current_mod_url)
                            if uuid_match:
                                uuid = uuid_match.group(1)
                                file_data = page.evaluate('''(uuid) => {
                                    return new Promise((resolve) => {
                                        fetch("/Verfahren/dxVUFilesForSupplier/" + uuid)
                                            .then(r => r.json()).then(data => resolve(data));
                                    });
                                }''', uuid)

                                for item in file_data:
                                    dok_id_str = item.get("DokIDStr")
                                    if dok_id_str:
                                        download_link = f"https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id={dok_id_str}"
                                        download_file(session, download_link, output_dir, saved)
                    except Exception as e:
                        print(f"Error handling deutsche-evergabe.de: {e}. Trying generic links.")

                    # Fallback to generic links on the page if JS extraction fails
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        if href and any(ext in href.lower() for ext in DOC_EXTS):
                            full_url = urljoin(base_url, href)
                            download_file(session, full_url, output_dir, saved)
                    browser.close()
                    return {"downloaded_files": saved}

                # bi-medien.de
                elif "bi-medien.de" in url or "deutsches-ausschreibungsblatt.de" in url:
                    page.wait_for_load_state("domcontentloaded")
                    page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay

                    # Find "Vergabeunterlagen" link that opens in new tab
                    vergabeunterlagen_link = page.locator('a:has-text("Vergabeunterlagen")').first
                    if vergabeunterlagen_link.is_visible():
                        with page.context.expect_page() as new_page_info:
                            vergabeunterlagen_link.click(timeout=10000)
                        new_page = new_page_info.value
                        new_page.wait_for_load_state("domcontentloaded")
                        new_page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay from new page

                        # Find "Unterlagen als ZIP-Datei" button/link
                        zip_link = new_page.locator('a:has-text("Unterlagen als ZIP-Datei")').first
                        if zip_link.is_visible():
                            href = zip_link.get_attribute("href")
                            if href:
                                full_url = urljoin(new_page.url, href)
                                if "getZip" in full_url: # Specific bi-medien pattern for ZIP
                                    download_file(session, full_url, output_dir, saved)
                                    if saved:
                                        new_page.close()
                                        browser.close()
                                        return {"downloaded_files": saved}
                        new_page.close()
                    
                    # Fallback to individual files on original page
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        if href and any(ext in href.lower() for ext in DOC_EXTS):
                            full_url = urljoin(base_url, href)
                            download_file(session, full_url, output_dir, saved)
                    browser.close()
                    return {"downloaded_files": saved}

                # vergabe24.de (bund.vergabe24.de)
                elif "vergabe24.de" in url:
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(3000)

                    # Check for NetServer redirect within vergabe24
                    netserver_redirect_link = page.locator('a[href*="/NetServer/"]').first
                    if netserver_redirect_link.is_visible():
                        netserver_href = netserver_redirect_link.get_attribute("href")
                        if netserver_href:
                            print(f"Redirecting to NetServer URL: {netserver_href}")
                            browser.close()
                            return scrape(netserver_href, output_dir) # Recurse with NetServer logic

                    # Standard vergabe24 flow
                    try:
                        # Click "Vergabeunterlagen anfordern"
                        request_docs_button = page.locator('button:has-text("Vergabeunterlagen anfordern")').first
                        if not request_docs_button.is_visible():
                            # Sometimes it might be a link or different text. Search broadly.
                            request_docs_button = page.locator('text=/Vergabeunterlagen anfordern|Zum Verfahren|Dokumente anzeigen/i').first
                            
                        request_docs_button.click(timeout=5000)
                        page.wait_for_timeout(2000) # Wait for popup

                        # Click "Unterlagen zur Ansicht herunterladen"
                        download_view_button = page.locator('button:has-text("Unterlagen zur Ansicht herunterladen")').first
                        download_view_button.click(timeout=5000)
                        page.wait_for_timeout(2000)

                        # Click "Weiter"
                        next_button = page.locator('button:has-text("Weiter")').first
                        next_button.click(timeout=5000)
                        page.wait_for_timeout(5000) # Wait for final page

                        # Find and download "Vergabeunterlagen als ZIP-Datei herunterladen"
                        zip_download_link = page.locator('a:has-text("Vergabeunterlagen als ZIP-Datei herunterladen")').first
                        if zip_download_link.is_visible():
                            with page.expect_download(timeout=30000) as download_info:
                                zip_download_link.click(timeout=15000)
                            download = download_info.value
                            file_path = Path(output_dir) / download.suggested_filename
                            download.save_as(str(file_path))
                            saved.append(str(file_path.resolve()))
                            print(f"Playwright downloaded Vergabe24 ZIP: {file_path}")
                            browser.close()
                            return {"downloaded_files": saved}
                    except Exception as e:
                        print(f"Error following vergabe24 multi-step process: {e}. Trying generic links.")

                    # Fallback if multi-step fails
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        if href and any(ext in href.lower() for ext in DOC_EXTS):
                            full_url = urljoin(base_url, href)
                            download_file(session, full_url, output_dir, saved)
                    browser.close()
                    return {"downloaded_files": saved}

                # SharePoint (:f: folder sharing links)
                elif ".sharepoint.com/:f:/" in url:
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(8000) # Wait for React/Fluent UI

                    try:
                        download_button = page.locator('button[name="Download"], [data-automationid="downloadCommand"]').first
                        if download_button.is_visible():
                            with page.expect_download(timeout=60000) as download_info: # Extended timeout for large downloads
                                download_button.click(timeout=20000)
                            download = download_info.value
                            file_path = Path(output_dir) / download.suggested_filename
                            download.save_as(str(file_path))
                            saved.append(str(file_path.resolve()))
                            print(f"Playwright downloaded SharePoint ZIP: {file_path}")
                    except Exception as e:
                        print(f"Could not find or click SharePoint download button: {e}. Proceeding.")

                    browser.close()
                    return {"downloaded_files": saved}

                # Ariba (eu.mu.ariba.com)
                elif "eu.mu.ariba.com" in url:
                    page.wait_for_load_state("networkidle")
                    page.wait_for_timeout(5000)

                    try:
                        # Scroll to Tender Documents section if necessary (might be on initial view)
                        # Ariba is complex, specific selectors might be needed, but 'Download All' is a common target
                        download_all_button = page.locator('button:has-text("Download All"), button:has-text("Alle herunterladen")').first
                        if download_all_button.is_visible():
                            download_all_button.scroll_into_view_if_needed(timeout=5000)
                            with page.expect_download(timeout=30000) as download_info:
                                download_all_button.click(timeout=15000)
                            download = download_info.value
                            file_path = Path(output_dir) / download.suggested_filename
                            download.save_as(str(file_path))
                            saved.append(str(file_path.resolve()))
                            print(f"Playwright downloaded Ariba ZIP: {file_path}")
                    except Exception as e:
                        print(f"Could not find or click Ariba 'Download All': {e}. Attempting individual links.")
                    
                    # Fallback to individual links
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        if href and any(ext in href.lower() for ext in DOC_EXTS):
                            full_url = urljoin(base_url, href)
                            download_file(session, full_url, output_dir, saved)
                    browser.close()
                    return {"downloaded_files": saved}

                # Default / Generic Scraper (if no platform matches or specific logic fails)
                print(f"No specific platform match or initial ZIP download failed for {url}. Falling back to generic link scraping.")
                for a_tag in page.locator('a[href]').all():
                    href = a_tag.get_attribute('href')
                    if href and any(ext in href.lower() for ext in DOC_EXTS):
                        full_url = urljoin(base_url, href)
                        # Basic filtering for common non-document links
                        if any(k in full_url.lower() for k in ["logout", "login", "javascript:void(0)", "mailto:", "tel:", "#", "facebook.com", "twitter.com", "linkedin.com"]):
                            continue
                        
                        # Try playwright download first if link is clickable and might trigger js.
                        # Otherwise, fall back to requests for direct hrefs.
                        try:
                            # Heuristic: if it's an immediate file extension, it's probably a direct download.
                            # If not, let playwright try a click if it's an inline "download" action.
                            if any(full_url.lower().endswith(ext) for ext in DOC_EXTS):
                                download_file(session, full_url, output_dir, saved)
                            else:
                                with page.expect_download(timeout=10000) as download_info:
                                    a_tag.click(timeout=5000)
                                download = download_info.value
                                file_path = Path(output_dir) / download.suggested_filename
                                download.save_as(str(file_path))
                                saved.append(str(file_path.resolve()))
                                print(f"Playwright downloaded generic link: {file_path}")
                        except Exception as dl_err:
                            print(f"Playwright download failed for {full_url}: {dl_err}. Trying requests for generic link.")
                            download_file(session, full_url, output_dir, saved)

            except Exception as page_exception:
                print(f"Error during Playwright page interaction for {url}: {page_exception}")

            browser.close()

    except Exception as e:
        print(f"An error occurred during the scraping process for {url}: {e}")

    return {"downloaded_files": saved}