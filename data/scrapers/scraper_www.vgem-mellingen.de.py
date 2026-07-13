import os, re, requests, hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import html

DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xml", ".xls", ".xlsx",
            ".ods", ".odt", ".gaeb", ".x81", ".x83", ".ppt", ".pptx", ".rar", ".7z", ".txt"}

def _download_file(session, url, output_dir, saved_files, filename=None):
    try:
        response = session.get(url, stream=True, timeout=10)
        response.raise_for_status()

        if filename is None:
            if 'content-disposition' in response.headers:
                fname_match = re.findall(r'filename\*?=(?:UTF-8\'\')?\"?([^\"]+)\"?', response.headers['content-disposition'])
                if fname_match:
                    filename = fname_match[0]
                    # Decode URL-encoded parts
                    filename = requests.utils.unquote(filename)
            if not filename:
                filename = os.path.basename(urlparse(url).path)
            if not filename or filename.startswith('.'): # Handle cases like '/path/'
                filename = "downloaded_file"

        # Ensure filename has a valid extension or add a generic one if needed
        file_ext = Path(filename).suffix.lower()
        if not file_ext or file_ext not in DOC_EXTS:
            content_type = response.headers.get('content-type', '').split(';')[0]
            if 'pdf' in content_type:
                filename = f"{filename.split('.')[0] or 'document'}.pdf"
            elif 'zip' in content_type:
                filename = f"{filename.split('.')[0] or 'archive'}.zip"
            elif 'xml' in content_type:
                filename = f"{filename.split('.')[0] or 'data'}.xml"
            elif 'excel' in content_type or 'spreadsheetml' in content_type:
                filename = f"{filename.split('.')[0] or 'spreadsheet'}.xlsx"
            elif 'word' in content_type or 'document' in content_type:
                filename = f"{filename.split('.')[0] or 'document'}.docx"
            else:
                # Fallback to unique name if still no good extension
                filename = f"{filename.split('.')[0] or 'file'}_{hashlib.md5(url.encode()).hexdigest()[:6]}.bin" # generic binary

        filepath = Path(output_dir) / filename
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        saved_files.append(str(filepath.resolve()))
        return True
    except requests.exceptions.RequestException as e:
        # print(f"Error downloading {url}: {e}")
        return False
    except Exception as e:
        # print(f"An unexpected error occurred while downloading {url}: {e}")
        return False

def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    saved_files = []
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    })

    try:
        if "evergabe.de" in url and "unterlagen" not in url:
            # Special handling for evergabe.de main tender page
            tender_id_match = re.search(r'(\d+)$', urlparse(url).path)
            if tender_id_match:
                tender_id = tender_id_match.group(1)
                doc_url = f"https://www.evergabe.de/unterlagen/{tender_id}"
                # print(f"Redirecting to evergabe.de documents page: {doc_url}")
                url = doc_url
                time.sleep(5) # Rate limiting for evergabe.de

        if any(platform in url for platform in ["/NetServer/", "tender24.de", "sachsen-vergabe.de",
                                               "vergabe.vmstart.de", "vergabe.landbw.de",
                                               "ausschreibungen.ls.brandenburg.de",
                                               "/PublicationControllerServlet?"]):
            # NetServer family
            parsed_url = urlparse(url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.split('/NetServer')[0]}/NetServer" if "/NetServer" in parsed_url.path else f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.split('/PublicationControllerServlet')[0]}"
            query_params = parse_qs(parsed_url.query)
            tender_oid = query_params.get('TenderOID') or query_params.get('TWOID')

            if tender_oid:
                tender_oid = tender_oid[0]
                # Try download all ZIP first
                zip_url = f"{base_url}/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={tender_oid}"

                # Try to get hidden fields for more specific ZIP URL construction
                try:
                    r = session.get(url, timeout=10)
                    r.raise_for_status()
                    soup = BeautifulSoup(r.text, 'html.parser')
                    form_inputs = {}
                    for inp in soup.find_all('input', type='hidden'):
                        form_inputs[inp.get('name')] = inp.get('value')
                    
                    if form_inputs.get('documentOID'):
                        zip_url += f"&documentOID={form_inputs['documentOID']}"
                    if form_inputs.get('TenderAuthority'):
                        zip_url += f"&TenderAuthority={form_inputs['TenderAuthority']}"
                    if form_inputs.get('TenderDate'):
                        zip_url += f"&TenderDate={form_inputs['TenderDate']}"
                    
                    if _download_file(session, zip_url, output_dir, saved_files):
                        # print(f"Downloaded NetServer ZIP: {zip_url}")
                        return {"downloaded_files": saved_files}
                except requests.exceptions.RequestException:
                    pass # Continue to individual files if ZIP fails

                # Fallback to individual files
                try:
                    r = session.get(url, timeout=10)
                    r.raise_for_status()
                    soup = BeautifulSoup(r.text, 'html.parser')
                    for a_tag in soup.find_all('a', href=True):
                        if "function=_DownloadDocument" in a_tag['href']:
                            doc_url = urljoin(base_url, a_tag['href'])
                            _download_file(session, doc_url, output_dir, saved_files)
                except requests.exceptions.RequestException:
                    pass

                return {"downloaded_files": saved_files} # Even if no files, return

            # If Direct TenderingProcedureDetails link is not in URL, try to find it
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE",
                                           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    # Look for links that lead to TenderingProcedureDetails
                    tp_link = page.locator('a[href*="TenderingProcedureDetails"]').first
                    if tp_link.is_visible():
                        url_to_follow = tp_link.get_attribute('href')
                        if url_to_follow:
                            page.goto(url_to_follow, wait_until="domcontentloaded", timeout=20000)
                            # Now retry the NetServer logic on this new page
                            parsed_url_tp = urlparse(url_to_follow)
                            base_url_tp = f"{parsed_url_tp.scheme}://{parsed_url_tp.netloc}{parsed_url_tp.path.split('/NetServer')[0]}/NetServer"
                            query_params_tp = parse_qs(parsed_url_tp.query)
                            tender_oid_tp = query_params_tp.get('TenderOID')

                            if tender_oid_tp:
                                tender_oid_tp = tender_oid_tp[0]
                                zip_url_tp = f"{base_url_tp}/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={tender_oid_tp}"
                                try:
                                    # Need a new session for the current page content
                                    r = session.get(url_to_follow, timeout=10)
                                    r.raise_for_status()
                                    soup = BeautifulSoup(r.text, 'html.parser')
                                    form_inputs = {}
                                    for inp in soup.find_all('input', type='hidden'):
                                        form_inputs[inp.get('name')] = inp.get('value')
                                    
                                    if form_inputs.get('documentOID'):
                                        zip_url_tp += f"&documentOID={form_inputs['documentOID']}"
                                    if form_inputs.get('TenderAuthority'):
                                        zip_url_tp += f"&TenderAuthority={form_inputs['TenderAuthority']}"
                                    if form_inputs.get('TenderDate'):
                                        zip_url_tp += f"&TenderDate={form_inputs['TenderDate']}"

                                    if _download_file(session, zip_url_tp, output_dir, saved_files):
                                        return {"downloaded_files": saved_files}
                                except requests.exceptions.RequestException:
                                    pass
                                
                                for a_tag in soup.find_all('a', href=True):
                                    if "function=_DownloadDocument" in a_tag['href']:
                                        doc_url = urljoin(base_url_tp, a_tag['href'])
                                        _download_file(session, doc_url, output_dir, saved_files)
                except PlaywrightTimeoutError:
                    pass # print(f"Playwright timeout while navigating NetServer page {url}")
                finally:
                    browser.close()
            # If still nothing, it might be a simple page with direct links
            r = session.get(url, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if href.lower().endswith(tuple(DOC_EXTS)):
                    doc_url = urljoin(url, href)
                    _download_file(session, doc_url, output_dir, saved_files)
            return {"downloaded_files": saved_files}


        if any(platform in url for platform in ["evergabe-online.de"]):
            # evergabe-online.de (Apache Wicket)
            r = session.get(url, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # Look for ZIP download button first
            for a_tag in soup.find_all('a', href=True):
                if 'zipDownloadButton' in a_tag['href']:
                    zip_url = urljoin(url, html.unescape(a_tag['href']))
                    if _download_file(session, zip_url, output_dir, saved_files):
                        return {"downloaded_files": saved_files}
            
            # If no ZIP, look for individual document links
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href'].lower()
                if any(href.endswith(ext) for ext in DOC_EXTS) and \
                   "login.html" not in href and "archivedProcedures.html" not in href:
                    doc_url = urljoin(url, a_tag['href'])
                    _download_file(session, doc_url, output_dir, saved_files)
            return {"downloaded_files": saved_files}

        if any(platform in url for platform in ["subreport.de", "subreport-elvis.de"]):
            # subreport.de (ELViS platform)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE",
                                           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_selector('body', state='attached', timeout=5000) # Wait for body to be present

                    # Click "anzeigen" to reveal document list
                    anzeigen_button = page.locator('button:has-text("anzeigen")')
                    if anzeigen_button.count() > 0:
                        anzeigen_button.first.click()
                        page.wait_for_timeout(5000) # Wait for content to load after click

                    # Look for the ZIP package or "Alle Dokumente" download
                    # Priority 1: <a> whose href ends with .zip or contains downloadall, alleherunterladen, alle-dokumente, archive
                    zip_link = page.locator('a[href$=".zip"], a[href*="downloadall"], a[href*="alleherunterladen"], a[href*="alle-dokumente"], a[href*="archive"]').first
                    if zip_link.is_visible():
                        with page.expect_download() as download_info:
                            zip_link.click()
                        download = download_info.value
                        download_path = Path(output_dir) / download.suggested_filename
                        download.save_as(download_path)
                        saved_files.append(str(download_path.resolve()))
                        return {"downloaded_files": saved_files}

                    # Priority 2: <a> or <button> whose visible text contains 'alle herunterladen' etc.
                    download_all_selectors = [
                        'a:has-text("alle herunterladen")',
                        'button:has-text("alle herunterladen")',
                        'a:has-text("alle dokumente")',
                        'a:has-text("alle als zip")',
                        'a:has-text("alles herunterladen")',
                        'a:has-text("download all")',
                        'a:has-text("download zip")',
                        'a:has-text("zip herunterladen")',
                        'a:has-text("unterlagen herunterladen")',
                        'a:has-text("alle unterlagen")',
                        'a:has-text("gesamtpaket")',
                        'a:has-text("vergabeunterlagen herunterladen")',
                    ]
                    for selector in download_all_selectors:
                        btn = page.locator(selector).first
                        if btn.is_visible():
                            with page.expect_download() as download_info:
                                btn.click()
                            download = download_info.value
                            download_path = Path(output_dir) / download.suggested_filename
                            download.save_as(download_path)
                            saved_files.append(str(download_path.resolve()))
                            return {"downloaded_files": saved_files}

                    # Specific for ELViS: find row containing "ZIP-Paket" or "Alle Dokumente" and click its "download" button.
                    # This often means finding a row with text and then locating a child button/link.
                    elements_containing_zip = page.query_selector_all('text="ZIP-Paket" || text="Alle Dokumente"')
                    for el in elements_containing_zip:
                        # Try to find a download button/link near it, often a sibling or parent descendant
                        parent_row = el.evaluate("node => node.closest('tr')")
                        if parent_row:
                            download_button = page.locator(f'xpath=//tr[./*[contains(text(), "ZIP-Paket") or contains(text(), "Alle Dokumente")]]//button[contains(@class, "download")] | //tr[./*[contains(text(), "ZIP-Paket") or contains(text(), "Alle Dokumente")]]//a[contains(@href, "download")]').first
                            if download_button.is_visible():
                                with page.expect_download() as download_info:
                                    download_button.click()
                                download = download_info.value
                                download_path = Path(output_dir) / download.suggested_filename
                                download.save_as(download_path)
                                saved_files.append(str(download_path.resolve()))
                                return {"downloaded_files": saved_files}

                    # Fallback to individual files
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        if href and any(href.lower().endswith(ext) for ext in DOC_EXTS):
                            full_url = urljoin(url, href)
                            try:
                                with page.expect_download() as download_info:
                                    a_tag.click()
                                download = download_info.value
                                download_path = Path(output_dir) / download.suggested_filename
                                download.save_as(download_path)
                                saved_files.append(str(download_path.resolve()))
                            except PlaywrightTimeoutError:
                                # Sometimes clicking individual links might not trigger a download in Playwright or is not intended
                                # Fallback to direct requests if Playwright fails to capture
                                if _download_file(session, full_url, output_dir, saved_files):
                                    pass # Successfully downloaded via requests
                except PlaywrightTimeoutError:
                    pass # print(f"Playwright timeout for subreport.de {url}")
                finally:
                    browser.close()
            return {"downloaded_files": saved_files}


        if any(platform in url for platform in ["evergabe", "vergabe.muenchen.de", "bieterportal.noncd.db.de",
                                               "kfw.vergabe.nrw.de", "vergabemarktplatz.brandenburg.de",
                                               "www.evergabe.bayern.de", "ausschreibungen.kfw.de"]) and "evergabe-online.de" not in url:
            # eVergabe 4.9 / Cosinex family (JS-rendered, requires Playwright)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE",
                                           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="networkidle", timeout=30000) # Use networkidle for JS-heavy pages
                    # Scroll down to ensure all elements are rendered or become visible
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(5000) # Wait for page to settle

                    # Try to find "Alle herunterladen" button directly
                    download_all_button = page.locator('button:has-text("Alle herunterladen")').first
                    if download_all_button.is_visible():
                        download_all_button.scroll_into_view_if_needed()
                        with page.expect_download() as download_info:
                            download_all_button.click()
                        download = download_info.value
                        download_path = Path(output_dir) / download.suggested_filename
                        download.save_as(download_path)
                        saved_files.append(str(download_path.resolve()))
                        return {"downloaded_files": saved_files}
                    
                    # If direct button not found, try clicking "Vergabeunterlagen" or "Teilnehmen" tab
                    vergabeunterlagen_tab = page.locator('button:has-text("Vergabeunterlagen")').first
                    teilnehmen_tab = page.locator('button:has-text("Teilnehmen")').first

                    if vergabeunterlagen_tab.is_visible():
                        vergabeunterlagen_tab.click()
                        page.wait_for_timeout(3000)
                        # Re-check for "Alle herunterladen" button
                        if download_all_button.is_visible():
                            download_all_button.scroll_into_view_if_needed()
                            with page.expect_download() as download_info:
                                download_all_button.click()
                            download = download_info.value
                            download_path = Path(output_dir) / download.suggested_filename
                            download.save_as(download_path)
                            saved_files.append(str(download_path.resolve()))
                            return {"downloaded_files": saved_files}
                    elif teilnehmen_tab.is_visible():
                        teilnehmen_tab.click()
                        page.wait_for_timeout(3000)
                        # Re-check for "Alle herunterladen" button
                        if download_all_button.is_visible():
                            download_all_button.scroll_into_view_if_needed()
                            with page.expect_download() as download_info:
                                download_all_button.click()
                            download = download_info.value
                            download_path = Path(output_dir) / download.suggested_filename
                            download.save_as(download_path)
                            saved_files.append(str(download_path.resolve()))
                            return {"downloaded_files": saved_files}

                    # Fallback to individual files if no "Alle herunterladen" was found
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        if href and any(href.lower().endswith(ext) for ext in DOC_EXTS):
                            try:
                                # Ensure link is visible before clicking
                                if a_tag.is_visible():
                                    full_url = urljoin(url, href)
                                    with page.expect_download() as download_info:
                                        a_tag.click()
                                    download = download_info.value
                                    download_path = Path(output_dir) / download.suggested_filename
                                    download.save_as(download_path)
                                    saved_files.append(str(download_path.resolve()))
                            except PlaywrightTimeoutError:
                                # Fallback to direct requests if playwright click fails or doesn't trigger download
                                if _download_file(session, urljoin(url, href), output_dir, saved_files):
                                    pass # Successfully downloaded via requests
                except PlaywrightTimeoutError:
                    pass # print(f"Playwright timeout for eVergabe 4.9 {url}")
                finally:
                    browser.close()
            return {"downloaded_files": saved_files}

        if "deutsche-evergabe.de" in url or "bieterzugang.deutsche-evergabe.de" in url:
            # deutsche-evergabe.de
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE",
                                           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(5000) # Wait for JS to render

                    # Click on "BekSummaries"
                    bek_summary_link = page.locator('a.BekSummary').first
                    if bek_summary_link.count() > 0:
                        bek_summary_link.click()
                        page.wait_for_timeout(5000) # Wait for modal to fully load
                        
                        current_url = page.url
                        uuid_match = re.search(r'/dashboards/dashboard_off/([a-f0-9-]+)', current_url)
                        if uuid_match:
                            uuid = uuid_match.group(1)
                            file_data = page.evaluate('''(uuid) => {
                                return new Promise((resolve) => {
                                    fetch("/Verfahren/dxVUFilesForSupplier/" + uuid)
                                        .then(r => r.json()).then(data => resolve(data));
                                });
                            }''', uuid)
                            
                            for item in file_data:
                                doc_id_str = item.get('DokID_Str')
                                if doc_id_str:
                                    download_url = f"https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id={doc_id_str}"
                                    if _download_file(session, download_url, output_dir, saved_files, filename=item.get('Filename')):
                                        pass
                except PlaywrightTimeoutError:
                    pass # print(f"Playwright timeout for deutsche-evergabe.de {url}")
                finally:
                    browser.close()
            return {"downloaded_files": saved_files}

        if any(platform in url for platform in ["bi-medien.de", "deutsches-ausschreibungsblatt.de"]):
            # bi-medien.de
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                # Create a fresh context for each site, locale and UA needs to be set
                ctx = browser.new_context(accept_downloads=True, locale="de-DE",
                                           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(3000) # Wait for initial page load including pop-ups

                    # Remove cookie overlay
                    page.evaluate('document.querySelector("#cmpwrapper")?.remove()')
                    # Other potential overlays
                    page.evaluate('document.querySelector(".cookie-notice")?.remove()')
                    page.evaluate('document.querySelector(".modal-backdrop")?.remove()')

                    # Look for "Vergabeunterlagen" link that opens a new tab
                    vergabeunterlagen_link = page.locator('a:has-text("Vergabeunterlagen")').first
                    if vergabeunterlagen_link.count() > 0:
                        with ctx.expect_page() as new_page_info:
                            vergabeunterlagen_link.click()
                        new_page = new_page_info.value
                        new_page.wait_for_load_state("domcontentloaded")
                        new_page.wait_for_timeout(3000) # Wait for new page content

                        # Remove overlays on the new page too
                        new_page.evaluate('document.querySelector("#cmpwrapper")?.remove()')
                        new_page.evaluate('document.querySelector(".cookie-notice")?.remove()')
                        new_page.evaluate('document.querySelector(".modal-backdrop")?.remove()')

                        # Find "Unterlagen als ZIP-Datei" on the new page
                        zip_download_link = new_page.locator('a:has-text("Unterlagen als ZIP-Datei")').first
                        if zip_download_link.count() > 0:
                            href = zip_download_link.get_attribute('href')
                            if href:
                                full_zip_url = urljoin(new_page.url, href)
                                if _download_file(session, full_zip_url, output_dir, saved_files):
                                    new_page.close()
                                    return {"downloaded_files": saved_files}
                        new_page.close()
                except PlaywrightTimeoutError:
                    pass # print(f"Playwright timeout for bi-medien.de {url}")
                finally:
                    browser.close()
            return {"downloaded_files": saved_files}
        
        if "vergabe24.de" in url or "bund.vergabe24.de" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE",
                                           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(3000)

                    # Check for NetServer redirect scenario
                    current_url = page.url
                    if "NetServer" in current_url:
                        # Re-run NetServer logic with this new URL
                        return scrape(current_url, output_dir)

                    # Multi-step
                    # 1. Click "Vergabeunterlagen anfordern"
                    vergabeunterlagen_anfordern_btn = page.locator('button:has-text("Vergabeunterlagen anfordern"), a:has-text("Vergabeunterlagen anfordern")').first
                    if vergabeunterlagen_anfordern_btn.is_visible():
                        vergabeunterlagen_anfordern_btn.click()
                        page.wait_for_timeout(2000) # Wait for popup

                        # 2. Click "Unterlagen zur Ansicht herunterladen" in popup
                        unterlagen_ansicht_btn = page.locator('button:has-text("Unterlagen zur Ansicht herunterladen")').first
                        if unterlagen_ansicht_btn.is_visible():
                            unterlagen_ansicht_btn.click()
                            page.wait_for_timeout(2000)

                            # 3. Click "Weiter"
                            weiter_btn = page.locator('button:has-text("Weiter")').first
                            if weiter_btn.is_visible():
                                weiter_btn.click()
                                page.wait_for_timeout(5000) # Wait for final page to load

                                # 4. Find "Vergabeunterlagen als ZIP-Datei herunterladen"
                                zip_download_btn = page.locator('button:has-text("Vergabeunterlagen als ZIP-Datei herunterladen")').first
                                if zip_download_btn.is_visible():
                                    with page.expect_download() as download_info:
                                        zip_download_btn.click()
                                    download = download_info.value
                                    download_path = Path(output_dir) / download.suggested_filename
                                    download.save_as(download_path)
                                    saved_files.append(str(download_path.resolve()))
                                    return {"downloaded_files": saved_files}
                except PlaywrightTimeoutError:
                    pass # print(f"Playwright timeout for vergabe24.de {url}")
                finally:
                    browser.close()
            return {"downloaded_files": saved_files}
        
        if "sharepoint.com" in url and ":f:" in url:
            # SharePoint folder sharing links
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE",
                                           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(8000) # Wait aggressively for React/Fluent UI

                    download_button = page.locator('button[name="Download"], [data-automationid="downloadCommand"]').first
                    if download_button.is_visible():
                        with page.expect_download() as download_info:
                            download_button.click()
                        download = download_info.value
                        download_path = Path(output_dir) / download.suggested_filename
                        download.save_as(download_path)
                        saved_files.append(str(download_path.resolve()))
                        return {"downloaded_files": saved_files}
                except PlaywrightTimeoutError:
                    pass # print(f"Playwright timeout for SharePoint {url}")
                finally:
                    browser.close()
            return {"downloaded_files": saved_files}

        if "eu.mu.ariba.com" in url:
            # Ariba
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE",
                                           user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="networkidle", timeout=30000)
                    page.wait_for_timeout(5000)

                    # Scroll to ensure elements are in view and loaded
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(2000)

                    download_all_button = page.locator('button:has-text("Download All"), button:has-text("Alle herunterladen")').first
                    if download_all_button.is_visible():
                        with page.expect_download() as download_info:
                            download_all_button.click()
                        download = download_info.value
                        download_path = Path(output_dir) / download.suggested_filename
                        download.save_as(download_path)
                        saved_files.append(str(download_path.resolve()))
                        return {"downloaded_files": saved_files}
                except PlaywrightTimeoutError:
                    pass # print(f"Playwright timeout for Ariba {url}")
                finally:
                    browser.close()
            return {"downloaded_files": saved_files}

        # DTVP (vergabeportal-bw.de and VMPSatellite/Satellite family)
        if "/Satellite/" in url or "/VMPSatellite/" in url:
            m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
            if m:
                project_id = m.group(1)
                prefix = "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"
                parts = urlparse(url)
                zip_url = f"{parts.scheme}://{parts.netloc}/{prefix}/public/company/project/{project_id}/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
                if _download_file(session, zip_url, output_dir, saved_files):
                    return {"downloaded_files": saved_files}
            # If ZIP not found or failed, try finding direct links
            try:
                r = session.get(url, timeout=10)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, 'html.parser')
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    if any(href.lower().endswith(ext) for ext in DOC_EXTS):
                        doc_url = urljoin(url, href)
                        _download_file(session, doc_url, output_dir, saved_files)
            except requests.exceptions.RequestException:
                pass
            return {"downloaded_files": saved_files}

        # Generic approach for other sites, prioritizing ZIPs/download all options
        r = session.get(url, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')

        # PRIORITY RULE 1: An <a> whose href ends with .zip or contains: downloadall, alleherunterladen, alle-dokumente, archive
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].lower()
            if href.endswith('.zip') or any(s in href for s in ['downloadall', 'alleherunterladen', 'alle-dokumente', 'archive']):
                zip_url = urljoin(url, a_tag['href'])
                if _download_file(session, zip_url, output_dir, saved_files):
                    return {"downloaded_files": saved_files}
        
        # PRIORITY RULE 2: An <a> or <button> whose visible text contains 'alle herunterladen' etc.
        download_all_patterns = [
            re.compile(r'alle herunterladen', re.IGNORECASE),
            re.compile(r'alle dokumente', re.IGNORECASE),
            re.compile(r'alle als zip', re.IGNORECASE),
            re.compile(r'alles herunterladen', re.IGNORECASE),
            re.compile(r'download all', re.IGNORECASE),
            re.compile(r'download zip', re.IGNORECASE),
            re.compile(r'zip herunterladen', re.IGNORECASE),
            re.compile(r'unterlagen herunterladen', re.IGNORECASE),
            re.compile(r'alle unterlagen', re.IGNORECASE),
            re.compile(r'gesamtpaket', re.IGNORECASE),
            re.compile(r'vergabeunterlagen herunterladen', re.IGNORECASE)
        ]

        for tag in soup.find_all(['a', 'button']):
            if tag.string:
                text = tag.string.strip()
                if any(pattern.search(text) for pattern in download_all_patterns):
                    href = tag.get('href')
                    if href:
                        zip_url = urljoin(url, href)
                        if _download_file(session, zip_url, output_dir, saved_files):
                            return {"downloaded_files": saved_files}
                    elif tag.name == 'button': # Button might trigger JS or have value
                        # For buttons, we often need Playwright. Use it if a button with these texts is found.
                        with sync_playwright() as p:
                            browser = p.chromium.launch(headless=True)
                            ctx = browser.new_context(accept_downloads=True, locale="de-DE",
                                                       user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                            page = ctx.new_page()
                            try:
                                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                                page.wait_for_timeout(3000)
                                button_locator = page.locator(f'{tag.name}:has-text("{text}")').first
                                if button_locator.is_visible():
                                    with page.expect_download() as download_info:
                                        button_locator.click()
                                    download = download_info.value
                                    download_path = Path(output_dir) / download.suggested_filename
                                    download.save_as(download_path)
                                    saved_files.append(str(download_path.resolve()))
                                    return {"downloaded_files": saved_files}
                            except PlaywrightTimeoutError:
                                pass
                            finally:
                                browser.close()

        # PRIORITY RULE 3: An <a> with an onclick= that constructs a ZIP download URL -> requires Playwright
        # This is harder to detect reliably with just BeautifulSoup.
        # Fallback to Playwright for general JS-driven downloads if prior static methods fail
        # This is commented out to avoid using Playwright for every generic site unless necessary.
        # If specific sites are known to use this, they should have dedicated Playwright logic above.

        # If no "download all" option exists -> download individual files
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            # Exclude common navigation/login/external links
            if any(href.lower().endswith(ext) for ext in DOC_EXTS) and \
               not any(s in href.lower() for s in ['login', 'javascript:', 'mailto:', 'tel:']) and \
               not urlparse(href).netloc or urlparse(href).netloc == parsed_url.netloc: # same domain or relative link
                doc_url = urljoin(url, href)
                _download_file(session, doc_url, output_dir, saved_files)

    except requests.exceptions.RequestException as e:
        # print(f"Request failed for {url}: {e}")
        pass
    except Exception as e:
        # print(f"An unexpected error occurred during scraping {url}: {e}")
        pass

    return {"downloaded_files": saved_files}

# BeautifulSoup import is typically at the top, adding here for independence
try:
    from bs4 import BeautifulSoup
except ImportError:
    # Fallback for environments where bs4 is not pre-installed
    # In a production environment, this should be handled by dependency management
    import collections
    class BeautifulSoup:
        def __init__(self, *args, **kwargs):
            raise ImportError("BeautifulSoup is not installed. Please install it with `pip install beautifulsoup4`")
        
        @staticmethod
        def find_all(*args, **kwargs):
            return []