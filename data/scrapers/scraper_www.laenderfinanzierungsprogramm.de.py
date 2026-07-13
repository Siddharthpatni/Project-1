import os, re, requests, hashlib, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import sync_playwright, Playwright

DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xml", ".xls", ".xlsx",
            ".ods", ".odt", ".gaeb", ".x81", ".x83", ".ppt", ".pptx", ".rar", ".7z", ".txt"}


def _is_doc_link(href: str) -> bool:
    """Checks if a URL points to a document based on its extension."""
    if not href:
        return False
    path = urlparse(href).path
    return any(path.lower().endswith(ext) for ext in DOC_EXTS)


def _download_file(session: requests.Session, url: str, output_dir: str, saved_files: list) -> None:
    """Downloads a file and saves it to the output directory."""
    try:
        response = session.get(url, stream=True, timeout=10)
        response.raise_for_status()

        # Determine filename
        content_disposition = response.headers.get('Content-Disposition')
        if content_disposition:
            fname_match = re.search(r'filename\*?=(?:UTF-8\'\')?\"?([^;\"]+)', content_disposition, re.IGNORECASE)
            if fname_match:
                filename = requests.utils.unquote(fname_match.group(1).strip())
            else:
                filename = Path(urlparse(url).path).name
        else:
            filename = Path(urlparse(url).path).name

        if not filename or filename.endswith('/'): # Fallback for no filename
            filename = hashlib.md5(url.encode()).hexdigest() + ".bin" # Generic name

        # Ensure filename has a common document extension if missing
        if not any(filename.lower().endswith(ext) for ext in DOC_EXTS):
            content_type = response.headers.get('Content-Type', '').lower()
            if 'pdf' in content_type:
                filename += '.pdf'
            elif 'zip' in content_type:
                filename += '.zip'
            elif 'xml' in content_type:
                filename += '.xml'
            elif 'spreadsheetml' in content_type or 'excel' in content_type:
                filename += '.xlsx'
            elif 'document' in content_type:
                filename += '.docx'
            else:
                # If still no valid extension, skip or assign generic
                print(f"Skipping download for {url} due to unknown file type and no suitable filename.")
                return

        filepath = os.path.join(output_dir, filename)

        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        saved_files.append(os.path.abspath(filepath))
        print(f"Downloaded: {filename}")
    except requests.exceptions.RequestException as e:
        print(f"Error downloading {url}: {e}")
    except Exception as e:
        print(f"Error processing {url}: {e}")


def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    saved_files = []
    session = requests.Session()

    try:
        if "NetServer/" in url or "tender24.de" in url or "sachsen-vergabe.de" in url or "vergabe.vmstart.de" in url or "vergabe.landbw.de" in url or "ausschreibungen.ls.brandenburg.de" in url:
            # NetServer family
            parsed_url = urlparse(url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{'/'.join(parsed_url.path.split('/')[:-1])}"
            query_params = parse_qs(parsed_url.query)
            tender_oid = query_params.get('TenderOID', [''])[0]

            if any(k in url for k in ["function=_Details", "function=Detail", "PublicationControllerServlet"]):
                # Try to construct download all ZIP URL
                zip_url = None
                if tender_oid:
                    zip_url = f"{base_url}/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={tender_oid}"
                    print(f"Attempting NetServer ZIP download: {zip_url}")
                    _download_file(session, zip_url, output_dir, saved_files)
                    if saved_files: # If ZIP was successfully downloaded, we are done
                        return {"downloaded_files": saved_files}

                # Fallback to Playwright for individual downloads or if ZIP construction failed
                print("Falling back to Playwright for NetServer individual documents or if ZIP failed.")
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                    page = ctx.new_page()
                    page.goto(url, wait_until="networkidle", timeout=30000)

                    # Look for "Download all" or "ZIP" links
                    zip_candidates = page.locator('a[href*=".zip"], a:has-text("download all"i), a:has-text("alle herunterladen"i), a:has-text("alle dokumente"i), a:has-text("alle als zip"i), a:has-text("alles herunterladen"i), a:has-text("download zip"i), a:has-text("zip herunterladen"i), a:has-text("unterlagen herunterladen"i), a:has-text("alle unterlagen"i), a:has-text("gesamtpaket"i), a:has-text("vergabeunterlagen herunterladen"i)')
                    if zip_candidates:
                        for i in range(zip_candidates.count()):
                            zip_link = zip_candidates.nth(i)
                            href = zip_link.get_attribute('href')
                            if href:
                                if "DownloadTenderDocuments" in href or ".zip" in href.lower() or "downloadall" in href.lower() or "alleherunterladen" in href.lower() or "alle-dokumente" in href.lower() or "archive" in href.lower():
                                    full_zip_url = urljoin(url, href)
                                    print(f"Found specific NetServer ZIP link via Playwright: {full_zip_url}")
                                    try:
                                        with page.expect_download() as download_info:
                                            zip_link.click(timeout=5000)
                                        download = download_info.value
                                        download_path = os.path.join(output_dir, download.suggested_filename)
                                        download.save_as(download_path)
                                        saved_files.append(os.path.abspath(download_path))
                                        print(f"Downloaded NetServer ZIP via Playwright: {download.suggested_filename}")
                                        return {"downloaded_files": saved_files}
                                    except Exception as dl_e:
                                        print(f"Could not download NetServer ZIP via Playwright click: {dl_e}")
                            else:
                                onclick_attr = zip_link.get_attribute('onclick')
                                if onclick_attr and ("DownloadTenderDocuments" in onclick_attr or "downloadall" in onclick_attr.lower()):
                                    # Attempt to extract URL from onclick or trigger somehow
                                    print(f"Found potential ZIP button with onclick: {onclick_attr}. Attempting click.")
                                    try:
                                        with page.expect_download() as download_info:
                                            zip_link.click(timeout=5000)
                                        download = download_info.value
                                        download_path = os.path.join(output_dir, download.suggested_filename)
                                        download.save_as(download_path)
                                        saved_files.append(os.path.abspath(download_path))
                                        print(f"Downloaded NetServer ZIP via Playwright (onclick): {download.suggested_filename}")
                                        return {"downloaded_files": saved_files}
                                    except Exception as dl_e:
                                        print(f"Could not download NetServer ZIP via Playwright onclick: {dl_e}")

                    # If no ZIP or 'download all' found, get individual documents
                    doc_links = page.locator('a[href*="function=_DownloadDocument"], a[href$=".pdf"], a[href$=".docx"], a[href$=".xls"], a[href$=".zip"], a[href$=".ppt"]')
                    for i in range(doc_links.count()):
                        link = doc_links.nth(i)
                        href = link.get_attribute('href')
                        if href and _is_doc_link(href):
                            full_url = urljoin(url, href)
                            try:
                                with page.expect_download() as download_info:
                                    link.click(timeout=5000)
                                download = download_info.value
                                download_path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(download_path)
                                saved_files.append(os.path.abspath(download_path))
                                print(f"Downloaded individual NetServer file: {download.suggested_filename}")
                            except Exception as dl_e:
                                print(f"Could not download individual file via Playwright click for {full_url}: {dl_e}")
                    browser.close()
                return {"downloaded_files": saved_files}

        elif "evergabe.de" in url and "unterlagen" not in url:
            # evergabe.de - direct to /unterlagen/{id}
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2) # Initial page load stabilization

                tender_id_match = re.search(r'(\d+)$', urlparse(url).path)
                if tender_id_match:
                    tender_id = tender_id_match.group(1)
                    documents_url = f"https://www.evergabe.de/unterlagen/{tender_id}"
                    print(f"Navigating to evergabe.de documents page: {documents_url}")
                    page.goto(documents_url, wait_until="networkidle", timeout=30000)
                    time.sleep(5) # Wait for JS to render document list

                    # Look for "Alle herunterladen" or similar
                    download_all_button = page.locator('button:has-text("Alle herunterladen"i)')
                    if download_all_button.count() > 0:
                        print("Found 'Alle herunterladen' button on evergabe.de. Attempting click.")
                        try:
                            with page.expect_download() as download_info:
                                download_all_button.first.click(timeout=5000)
                            download = download_info.value
                            download_path = os.path.join(output_dir, download.suggested_filename)
                            download.save_as(download_path)
                            saved_files.append(os.path.abspath(download_path))
                            print(f"Downloaded evergabe.de ZIP: {download.suggested_filename}")
                            browser.close()
                            return {"downloaded_files": saved_files}
                        except Exception as dl_e:
                            print(f"Could not download evergabe.de ZIP via click: {dl_e}")
                            # Continue to individual if ZIP fails

                    doc_links = page.locator('a:has-text("Datei herunterladen"i), a[href*=".pdf"], a[href*=".zip"], a[href*=".docx"], a[href*=".xls"], a[href*=".gaeb"]')
                    for i in range(doc_links.count()):
                        link = doc_links.nth(i)
                        href = link.get_attribute('href')
                        if href and _is_doc_link(href):
                            full_url = urljoin(documents_url, href)
                            try:
                                print(f"Attempting to download individual evergabe.de file: {full_url}")
                                with page.expect_download() as download_info:
                                    link.click(timeout=5000)
                                download = download_info.value
                                download_path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(download_path)
                                saved_files.append(os.path.abspath(download_path))
                                print(f"Downloaded individual evergabe.de file: {download.suggested_filename}")
                                time.sleep(5) # Rate limit
                            except Exception as dl_e:
                                print(f"Could not download individual file via Playwright click for {full_url}: {dl_e}")
                browser.close()
                return {"downloaded_files": saved_files}

        elif "eVergabe" in url or "vergabe.nrw.de" in url or "vergabemarktplatz.brandenburg.de" in url or "vergabe.muenchen.de" in url or "bieterportal.noncd.db.de" in url or "www.evergabe.bayern.de" in url or "ausschreibungen.kfw.de" in url:
            # Cosinex / eVergabe 4.9 family (Angular app)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                print("Waiting 8 seconds for eVergabe 4.9 JS to render...")
                page.wait_for_timeout(8000) # Wait for Angular app to fully render

                # Try clicking 'Vergabeunterlagen' tab if it exists
                vergabeunterlagen_tab = page.locator('button:has-text("Vergabeunterlagen"i)')
                if vergabeunterlagen_tab.count() > 0 and vergabeunterlagen_tab.is_visible():
                    print("Clicking 'Vergabeunterlagen' tab.")
                    vergabeunterlagen_tab.click()
                    page.wait_for_timeout(3000) # Wait for tab content to load

                # Find and click "Alle herunterladen" button
                download_all_button = page.locator('button:has-text("Alle herunterladen"i)')
                if download_all_button.count() > 0 and download_all_button.is_visible():
                    print("Found 'Alle herunterladen' button for eVergabe 4.9. Attempting click.")
                    try:
                        download_all_button.scroll_into_view_if_needed()
                        with page.expect_download() as download_info:
                            download_all_button.click(timeout=10000) # Increased timeout for download
                        download = download_info.value
                        download_path = os.path.join(output_dir, download.suggested_filename)
                        download.save_as(download_path)
                        saved_files.append(os.path.abspath(download_path))
                        print(f"Downloaded eVergabe 4.9 ZIP: {download.suggested_filename}")
                        browser.close()
                        return {"downloaded_files": saved_files}
                    except Exception as dl_e:
                        print(f"Could not download eVergabe 4.9 ZIP via click: {dl_e}")
                else:
                    print(f"'Alle herunterladen' button not found on {url}.")

                # Fallback to individual
                print("Falling back to individual document download for eVergabe 4.9.")
                doc_links = page.locator('a[download], a[href*="documentId"], a[href$=".pdf"], a[href$=".docx"], a[href$=".xls"], a[href$=".zip"]')
                for i in range(doc_links.count()):
                    link_elem = doc_links.nth(i)
                    href = link_elem.get_attribute('href')
                    if href and _is_doc_link(href):
                        full_url = urljoin(url, href)
                        try:
                            # Use expect_download because many are dynamic clicks
                            with page.expect_download() as download_info:
                                link_elem.click(timeout=5000)
                            download = download_info.value
                            download_path = os.path.join(output_dir, download.suggested_filename)
                            download.save_as(download_path)
                            saved_files.append(os.path.abspath(download_path))
                            print(f"Downloaded individual eVergabe 4.9 file: {download.suggested_filename}")
                        except Exception as dl_e:
                             print(f"Could not download individual eVergabe 4.9 file via Playwright click for {full_url}: {dl_e}")
                browser.close()
                return {"downloaded_files": saved_files}

        elif "evergabe-online.de" in url:
            # evergabe-online.de (Apache Wicket)
            response = session.get(url, timeout=10)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            zip_found = False
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if "zipDownloadButton" in href:
                    unescaped_href = htmllib.unescape(href)
                    full_zip_url = urljoin(url, unescaped_href)
                    if not any(excluded_string in full_zip_url for excluded_string in ['archivedProcedures.html', 'login.html']):
                        print(f"Found evergabe-online.de ZIP link: {full_zip_url}")
                        _download_file(session, full_zip_url, output_dir, saved_files)
                        zip_found = True
                        break # Only one ZIP download is expected

            if zip_found and saved_files:
                return {"downloaded_files": saved_files}

            # If no zip found or failed, look for individual files
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if _is_doc_link(href):
                    full_url = urljoin(url, href)
                    if not any(excluded_string in full_url for excluded_string in ['archivedProcedures.html', 'login.html']):
                         _download_file(session, full_url, output_dir, saved_files)
            return {"downloaded_files": saved_files}

        elif "subreport.de" in url or "subreport-elvis.de" in url:
            # subreport / ELViS platform
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000) # Initial stabilization

                # Click "anzeigen" button to reveal documents
                anzeigen_button = page.locator('button:has-text("anzeigen"i)')
                if anzeigen_button.count() > 0 and anzeigen_button.is_visible():
                    print("Clicking 'anzeigen' button on subreport.")
                    anzeigen_button.click()
                    page.wait_for_timeout(5000) # Wait for documents to load

                # Look for "ZIP-Paket" or "Alle Dokumente" download button
                zip_row = page.locator('text=/ZIP-Paket|Alle Dokumente/').first
                if zip_row.count() > 0:
                    download_button = zip_row.locator('xpath=./ancestor::tr//button[contains(@class, "btn-download")] | ./ancestor::tr//a[contains(@class, "btn-download")]').first
                    if download_button.is_visible():
                        print("Found 'ZIP-Paket' or 'Alle Dokumente' download button on subreport. Attempting click.")
                        try:
                            with page.expect_download() as download_info:
                                download_button.click(timeout=10000)
                            download = download_info.value
                            download_path = os.path.join(output_dir, download.suggested_filename)
                            download.save_as(download_path)
                            saved_files.append(os.path.abspath(download_path))
                            print(f"Downloaded subreport ZIP: {download.suggested_filename}")
                            browser.close()
                            return {"downloaded_files": saved_files}
                        except Exception as dl_e:
                            print(f"Could not download subreport ZIP via click: {dl_e}")

                # Fallback to individual
                print("Falling back to individual document download for subreport.")
                doc_buttons = page.locator('button[class*="btn-download"], a[class*="btn-download"]')
                for i in range(doc_buttons.count()):
                    btn = doc_buttons.nth(i)
                    if btn.is_visible():
                        try:
                            with page.expect_download() as download_info:
                                btn.click(timeout=5000)
                            download = download_info.value
                            download_path = os.path.join(output_dir, download.suggested_filename)
                            download.save_as(download_path)
                            saved_files.append(os.path.abspath(download_path))
                            print(f"Downloaded individual subreport file: {download.suggested_filename}")
                        except Exception as dl_e:
                            print(f"Could not download individual subreport file via Playwright click: {dl_e}")
                browser.close()
                return {"downloaded_files": saved_files}

        elif "deutsche-evergabe.de" in url or "bieterzugang.deutsche-evergabe.de" in url:
            # deutsche-evergabe.de
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000) # Wait for JS to load

                if "bieterzugang" in url:
                    # Follow redirect to main site if it happened
                    current_url = page.url
                    if "deutsche-evergabe.de" not in current_url:
                        print(f"bieterzugang redirected to {current_url}. Following...")
                        url = current_url
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(5000)

                # Click the summary link to open the modal
                bek_summary = page.locator('a.BekSummary').first
                if bek_summary.count() > 0:
                    print("Clicking a.BekSummary on deutsche-evergabe.de")
                    bek_summary.click()
                    page.wait_for_timeout(5000) # Wait for modal to load

                    current_url = page.url
                    uuid_match = re.search(r'/dashboards/dashboard_off/([0-9a-fA-F-]+)', current_url)
                    if uuid_match:
                        uuid = uuid_match.group(1)
                        print(f"Extracted UUID: {uuid}")
                        try:
                            file_data = page.evaluate('''(uuid) => {
                                return new Promise((resolve, reject) => {
                                    fetch("/Verfahren/dxVUFilesForSupplier/" + uuid)
                                        .then(r => r.json())
                                        .then(data => resolve(data))
                                        .catch(err => reject(err));
                                });
                            }''', uuid)

                            if file_data and isinstance(file_data, list):
                                print(f"Found {len(file_data)} files via JS API for deutsche-evergabe.de.")
                                for file_info in file_data:
                                    doc_id_str = file_info.get('DokIDStr')
                                    if doc_id_str:
                                        download_url = f"https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id={doc_id_str}"
                                        _download_file(session, download_url, output_dir, saved_files)
                        except Exception as js_e:
                            print(f"Error fetching files via JS for deutsche-evergabe.de: {js_e}")
                    else:
                        print("Could not extract UUID from URL for deutsche-evergabe.de")
                else:
                    print("BekSummary link not found on deutsche-evergabe.de.")

                browser.close()
                return {"downloaded_files": saved_files}

        elif "bi-medien.de" in url or "deutsches-ausschreibungsblatt.de" in url:
            # bi-medien.de / deutsches-ausschreibungsblatt.de
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000) # Wait for initial JS
                page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay

                # Click "Vergabeunterlagen" link (may open new tab)
                vergabeunterlagen_link = page.locator('a:has-text("Vergabeunterlagen"i)')
                if vergabeunterlagen_link.count() > 0:
                    print("Found 'Vergabeunterlagen' link on bi-medien.de. Attempting click.")
                    with ctx.expect_page() as new_page_info:
                        vergabeunterlagen_link.click(timeout=10000)
                    new_page = new_page_info.value
                    new_page.wait_for_load_state("networkidle", timeout=30000)
                    new_page.wait_for_timeout(3000)
                    new_page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay again

                    zip_link = new_page.locator('a:has-text("Unterlagen als ZIP-Datei"i)')
                    if zip_link.count() > 0:
                        href = zip_link.get_attribute('href')
                        if href:
                            full_zip_url = urljoin(new_page.url, href)
                            print(f"Found bi-medien.de ZIP link: {full_zip_url}. Attempting download.")
                            try:
                                with new_page.expect_download() as download_info:
                                    zip_link.click(timeout=10000)
                                download = download_info.value
                                download_path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(download_path)
                                saved_files.append(os.path.abspath(download_path))
                                print(f"Downloaded bi-medien.de ZIP: {download.suggested_filename}")
                                browser.close()
                                return {"downloaded_files": saved_files}
                            except Exception as dl_e:
                                print(f"Could not download bi-medien.de ZIP via Playwright click: {dl_e}")
                    else:
                        print("ZIP link not found on bi-medien.de documents page. Looking for individual files.")
                        doc_links = new_page.locator('a[href$=".pdf"], a[href$=".docx"], a[href$=".xls"], a[href$=".zip"]')
                        for i in range(doc_links.count()):
                            link_elem = doc_links.nth(i)
                            href = link_elem.get_attribute('href')
                            if href and _is_doc_link(href):
                                full_url = urljoin(new_page.url, href)
                                try:
                                    with new_page.expect_download() as download_info:
                                        link_elem.click(timeout=5000)
                                    download = download_info.value
                                    download_path = os.path.join(output_dir, download.suggested_filename)
                                    download.save_as(download_path)
                                    saved_files.append(os.path.abspath(download_path))
                                    print(f"Downloaded individual bi-medien.de file: {download.suggested_filename}")
                                except Exception as dl_e:
                                     print(f"Could not download individual bi-medien.de file via Playwright click for {full_url}: {dl_e}")

                    new_page.close()
                browser.close()
                return {"downloaded_files": saved_files}

        elif "vergabe24.de" in url or "bund.vergabe24.de" in url:
            # vergabe24.de
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()

                # FIRST, check if it's a redirect to NetServer
                initial_response = page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if "NetServer/" in page.url:
                    print(f"vergabe24.de redirected to NetServer: {page.url}. Re-processing with NetServer logic.")
                    browser.close()
                    return scrape(page.url, output_dir) # RECURSIVE CALL for NetServer
                page.wait_for_timeout(3000)

                # Step 1: Click "Vergabeunterlagen anfordern"
                anfordern_button = page.locator('a:has-text("Vergabeunterlagen anfordern"i), button:has-text("Vergabeunterlagen anfordern"i)').first
                if anfordern_button.count() > 0:
                    print("Clicking 'Vergabeunterlagen anfordern' on vergabe24.de")
                    anfordern_button.click(timeout=5000)
                    page.wait_for_timeout(2000) # Wait for popup/next step

                    # Step 2: Click "Unterlagen zur Ansicht herunterladen" (in popup/next page)
                    ansicht_button = page.locator('a:has-text("Unterlagen zur Ansicht herunterladen"i), button:has-text("Unterlagen zur Ansicht herunterladen"i)').first
                    if ansicht_button.count() > 0:
                        print("Clicking 'Unterlagen zur Ansicht herunterladen'")
                        ansicht_button.click(timeout=5000)
                        page.wait_for_timeout(2000)

                        # Step 3: Click "Weiter"
                        weiter_button = page.locator('button:has-text("Weiter"i)').first
                        if weiter_button.count() > 0:
                            print("Clicking 'Weiter'")
                            weiter_button.click(timeout=5000)
                            page.wait_for_load_state("domcontentloaded", timeout=10000)
                            page.wait_for_timeout(3000)

                            # Step 4: Find and download "Vergabeunterlagen als ZIP-Datei herunterladen"
                            zip_download_link = page.locator('a:has-text("Vergabeunterlagen als ZIP-Datei herunterladen"i)').first
                            if zip_download_link.count() > 0:
                                print("Found vergabe24.de ZIP download link. Attempting click.")
                                try:
                                    with page.expect_download() as download_info:
                                        zip_download_link.click(timeout=10000)
                                    download = download_info.value
                                    download_path = os.path.join(output_dir, download.suggested_filename)
                                    download.save_as(download_path)
                                    saved_files.append(os.path.abspath(download_path))
                                    print(f"Downloaded vergabe24.de ZIP: {download.suggested_filename}")
                                    browser.close()
                                    return {"downloaded_files": saved_files}
                                except Exception as dl_e:
                                    print(f"Could not download vergabe24.de ZIP via Playwright click: {dl_e}")
                            else:
                                print("Vergabeunterlagen als ZIP-Datei herunterladen' link not found.")
                        else:
                            print("'Weiter' button not found.")
                    else:
                        print("'Unterlagen zur Ansicht herunterladen' button not found.")
                else:
                    print("'Vergabeunterlagen anfordern' button not found.")
                browser.close()
                return {"downloaded_files": saved_files}

        elif ":f:/s/" in url and "sharepoint.com" in url:
            # SharePoint folder sharing link
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                page.goto(url, wait_until="networkidle", timeout=45000) # Increased timeout for SharePoint
                print("Waiting 10 seconds for SharePoint to render...")
                page.wait_for_timeout(10000) # Wait for React/Fluent UI to render

                download_button = page.locator('button[name="Download"], [data-automationid="downloadCommand"]').first
                if download_button.count() > 0 and download_button.is_visible():
                    print("Found SharePoint 'Download' button. Attempting click.")
                    try:
                        download_button.scroll_into_view_if_needed()
                        with page.expect_download() as download_info:
                            download_button.click(timeout=15000) # Increased timeout for large downloads
                        download = download_info.value
                        download_path = os.path.join(output_dir, download.suggested_filename)
                        download.save_as(download_path)
                        saved_files.append(os.path.abspath(download_path))
                        print(f"Downloaded SharePoint ZIP: {download.suggested_filename}")
                        browser.close()
                        return {"downloaded_files": saved_files}
                    except Exception as dl_e:
                        print(f"Could not download SharePoint ZIP via click: {dl_e}")
                else:
                    print("SharePoint 'Download' button not found.")
                browser.close()
                return {"downloaded_files": saved_files}

        elif "eu.mu.ariba.com" in url:
            # Ariba
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(accept_downloads=True, locale="de-DE", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                page.goto(url, wait_until="networkidle", timeout=30000)
                print("Waiting 8 seconds for Ariba to render...")
                page.wait_for_timeout(8000)

                # Scroll to and click "Download All"
                download_all_button = page.locator('button:has-text("Download All"i)').first
                if download_all_button.count() > 0 and download_all_button.is_visible():
                    print("Found Ariba 'Download All' button. Attempting click.")
                    try:
                        download_all_button.scroll_into_view_if_needed()
                        with page.expect_download() as download_info:
                            download_all_button.click(timeout=10000)
                        download = download_info.value
                        download_path = os.path.join(output_dir, download.suggested_filename)
                        download.save_as(download_path)
                        saved_files.append(os.path.abspath(download_path))
                        print(f"Downloaded Ariba ZIP: {download.suggested_filename}")
                        browser.close()
                        return {"downloaded_files": saved_files}
                    except Exception as dl_e:
                        print(f"Could not download Ariba ZIP via click: {dl_e}")
                else:
                    print("Ariba 'Download All' button not found.")

                browser.close()
                return {"downloaded_files": saved_files}

        elif "/Satellite/" in url or "/VMPSatellite/" in url:
            # DTVP (vergabeportal-bw.de and VMPSatellite/Satellite family)
            m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
            if m:
                project_id = m.group(1)
                prefix = "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"
                parts = urlparse(url)
                zip_url = f"{parts.scheme}://{parts.netloc}/{prefix}/public/company/project/{project_id}/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
                print(f"Attempting DTVP ZIP download: {zip_url}")
                _download_file(session, zip_url, output_dir, saved_files)
                if saved_files:
                    return {"downloaded_files": saved_files}
            print("DTVP specific ZIP construction failed or no project ID found. Proceeding with generic link parsing.")
            # Fallback to generic link parsing if direct ZIP fails for DTVP
            # This part will be covered by the generic scraping logic if no specific logic matched initially.

        # ----- Generic/Fallback Strategy for all other cases and if specific failed -----
        print(f"Applying generic scraping strategy for {url}")
        
        # Check for direct ZIP/download all links first using requests
        response = session.get(url, timeout=10)
        response.raise_for_status()
        from bs4 import BeautifulSoup
        import html as htmllib
        soup = BeautifulSoup(response.text, 'html.parser')

        # Priority 1: <a> whose href ends with .zip or contains downloadall, alleherunterladen, etc.
        zip_links_href = soup.find_all('a', href=re.compile(r'\.(zip|downloadall|alleherunterladen|alle-dokumente|archive)', re.IGNORECASE))
        for a_tag in zip_links_href:
            href = a_tag['href']
            full_zip_url = urljoin(url, href)
            print(f"Found generic ZIP link (href pattern): {full_zip_url}")
            _download_file(session, full_zip_url, output_dir, saved_files)
            if saved_files: return {"downloaded_files": saved_files}

        # Priority 2: <a> or <button> whose visible text contains "alle herunterladen", etc.
        zip_text_patterns = re.compile(
            r'alle herunterladen|alle dokumente|alle als zip|alles herunterladen|'
            r'download all|download zip|zip herunterladen|unterlagen herunterladen|'
            r'alle unterlagen|gesamtpaket|vergabeunterlagen herunterladen',
            re.IGNORECASE
        )
        zip_links_text = soup.find_all(['a', 'button'], string=zip_text_patterns)
        for a_tag in zip_links_text:
            href = a_tag.get('href')
            if href:
                full_zip_url = urljoin(url, href)
                print(f"Found generic ZIP link (text pattern): {full_zip_url}")
                _download_file(session, full_zip_url, output_dir, saved_files)
                if saved_files: return {"downloaded_files": saved_files}

        # Priority 3: <a> with an onclick= that constructs a ZIP download URL (heuristic)
        for a_tag in soup.find_all('a', onclick=True):
            onclick_attr = a_tag['onclick']
            if any(key_word in onclick_attr.lower() for key_word in ['zip', 'download', 'archive', 'alleherunterladen']):
                href = a_tag.get('href')
                if href and _is_doc_link(href): # If href is also a doc link, try it
                   full_zip_url = urljoin(url, href)
                   print(f"Found generic ZIP link (onclick + href heuristic): {full_zip_url}")
                   _download_file(session, full_zip_url, output_dir, saved_files)
                   if saved_files: return {"downloaded_files": saved_files}
                # Else, if no direct href, assume it's a JS function. Playwright needed.
                # Since this is generic/requests path, we can't execute JS.
                # So we prioritize hrefs.

        if saved_files: # If a ZIP was downloaded by generic methods, we are done
            return {"downloaded_files": saved_files}

        # If no "download all" option exists, download individual files.
        # This part will run if no specific platform logic or generic ZIP download succeeded.
        print("No 'download all' ZIP found. Attempting to download individual documents.")
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href']
            if _is_doc_link(href):
                full_url = urljoin(url, href)
                # Filter out obvious non-document links
                if not any(nav_kw in full_url.lower() for nav_kw in ['login', 'register', 'mailto', 'tel:']):
                    _download_file(session, full_url, output_dir, saved_files)

    except Exception as e:
        print(f"An unexpected error occurred during scraping for {url}: {e}")
    finally:
        # Close Playwright browser if it was opened and still active
        if 'browser' in locals() and browser:
            try:
                browser.close()
            except Exception as e:
                print(f"Error closing browser: {e}")

    return {"downloaded_files": saved_files}