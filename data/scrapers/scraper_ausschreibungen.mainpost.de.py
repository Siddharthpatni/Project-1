import os, re, requests, hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import html
import time

DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xls", ".xlsx",
            ".ods", ".odt", ".gaeb", ".x81", ".x83", ".ppt", ".pptx", ".rar", ".7z", ".txt", ".xml"}

def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    
    def save_file(response_content, filename_suggestion, url):
        # Infer extension from content-type if not in filename_suggestion
        ext = Path(filename_suggestion).suffix.lower()
        if not ext or ext not in DOC_EXTS:
            content_type = response_content.headers.get('content-type', '').split(';')[0]
            if 'pdf' in content_type:
                ext = '.pdf'
            elif 'zip' in content_type:
                ext = '.zip'
            elif 'xml' in content_type:
                ext = '.xml'
            elif 'excel' in content_type or 'spreadsheetml' in content_type:
                ext = '.xlsx' # Default for excel
            elif 'wordprocessingml' in content_type:
                ext = '.docx' # Default for word
            elif 'powerpoint' in content_type:
                ext = '.pptx'
            elif 'text' in content_type:
                ext = '.txt'

        base_filename = Path(filename_suggestion).stem
        final_filename = f"{base_filename}{ext}" if ext else filename_suggestion
        
        # Ensure unique filename if it already exists
        count = 1
        path = Path(output_dir) / final_filename
        while path.exists():
            final_filename = f"{base_filename}_{count}{ext}" if ext else f"{filename_suggestion}_{count}"
            path = Path(output_dir) / final_filename
            count += 1

        try:
            with open(path, 'wb') as f:
                f.write(response_content.content)
            saved.append(str(path.resolve()))
            print(f"Downloaded: {path.name}")
        except Exception as e:
            print(f"Error saving file {final_filename}: {e}")

    try:
        if "NetServer" in url or "PublicationControllerServlet" in url:
            # NetServer family
            if "function=_Details" in url or "function=Detail" in url:
                parsed_url = urlparse(url)
                query_params = parse_qs(parsed_url.query)
                tender_oid = query_params.get("TenderOID", [None])[0]

                if tender_oid:
                    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{parsed_url.path.split('?')[0]}"
                    download_all_url = f"{base_url}?function=_DownloadTenderDocuments&TenderOID={tender_oid}"
                    
                    # Try to find additional parameters for DownloadTenderDocuments
                    try:
                        resp = requests.get(url, timeout=10)
                        resp.raise_for_status()
                        soup = BeautifulSoup(resp.content, 'html.parser')
                        form = soup.find('form', id='aspnetForm')
                        if form:
                            hidden_inputs = form.find_all('input', type='hidden')
                            params = {inp['name']: inp['value'] for inp in hidden_inputs if 'name' in inp and 'value' in inp}
                            # Check if these params are already in the URL from the tender details page itself
                            for key, value in query_params.items():
                                if key not in params:
                                    params[key] = value[0]
                            
                            # Reconstruct URL with additional params if needed
                            if params and (len(params) > 1 or ("TenderOID" not in params and tender_oid)): # Only add if there are actual new params
                                download_all_url_parts = [f"{base_url}?function=_DownloadTenderDocuments"]
                                # Prioritize TenderOID found from URL if it exists
                                if tender_oid and "TenderOID" not in params:
                                    download_all_url_parts.append(f"TenderOID={tender_oid}")

                                for k, v in params.items():
                                    if k != "__VIEWSTATE" and k != "__EVENTVALIDATION": # Skip these
                                        if k == 'TenderOID' and tender_oid and tender_oid != v: # Prefer tender_oid from URL
                                            download_all_url_parts.append(f"{k}={tender_oid}")
                                        else:
                                            download_all_url_parts.append(f"{k}={v}")
                                download_all_url = "&".join(download_all_url_parts)
                                # Clean up duplicate parameters in URL
                                current_params = parse_qs(urlparse(download_all_url).query)
                                unique_params = {}
                                for k, v in current_params.items():
                                    if k not in unique_params:
                                        unique_params[k] = v[0] if v else ""
                                download_all_url = f"{base_url}?function=_DownloadTenderDocuments&{'&'.join(f'{k}={v}' for k,v in unique_params.items())}"

                    except requests.exceptions.RequestException as e:
                        print(f"Could not retrieve page content for NetServer parameter parsing: {e}")
                        pass # Continue with simpler URL if parsing fails

                    print(f"Trying NetServer download all URL: {download_all_url}")
                    try:
                        response = requests.get(download_all_url, stream=True, timeout=10)
                        response.raise_for_status()
                        if 'application/zip' in response.headers.get('Content-Type', '').lower() or \
                           'application/octet-stream' in response.headers.get('Content-Type', '').lower() and \
                           '.zip' in response.headers.get('Content-Disposition', '').lower():
                            filename = response.headers.get("Content-Disposition", f"NetServer_Documents_{tender_oid}.zip").split("filename=")[-1].strip('"\'')
                            save_file(response, filename, download_all_url)
                            return {"downloaded_files": saved}
                        else:
                            print("NetServer download all failed or was not a zip. Falling back to individual files.")
                    except requests.exceptions.RequestException as e:
                        print(f"Failed to download NetServer ZIP: {e}")

                # If download all failed or not found, try individual links
                try:
                    resp = requests.get(url, timeout=10)
                    resp.raise_for_status()
                    soup = BeautifulSoup(resp.content, 'html.parser')
                    for a_tag in soup.find_all('a', href=True):
                        link_href = a_tag['href']
                        if "function=_DownloadDocument" in link_href:
                            full_download_url = urljoin(url, link_href)
                            try:
                                file_resp = requests.get(full_download_url, stream=True, timeout=10)
                                file_resp.raise_for_status()
                                filename = file_resp.headers.get("Content-Disposition", urlparse(full_download_url).path.split('/')[-1]).split("filename=")[-1].strip('"\'')
                                save_file(file_resp, filename, full_download_url)
                            except requests.exceptions.RequestException as e:
                                print(f"Failed to download individual NetServer file {full_download_url}: {e}")
                except requests.exceptions.RequestException as e:
                    print(f"Failed to get NetServer page for individual files: {e}")
            return {"downloaded_files": saved}

        elif "evergabe.de" in url or "bieterportal.noncd.db.de" in url or "vergabe.muenchen.de" in url or \
             "evergabe-online.de" in url or "subreport.de" in url or "subreport-elvis.de" in url or \
             "deutsche-evergabe.de" in url or "bi-medien.de" in url or "deutsches-ausschreibungsblatt.de" in url or \
             "vergabe24.de" in url or "bund.vergabe24.de" in url or ":f:/s/" in url or \
             "eu.mu.ariba.com" in url or "kfw.vergabe.nrw.de" in url or "vergabemarktplatz.brandenburg.de" in url or \
             "www.evergabe.bayern.de" in url or "ausschreibungen.kfw.de" in url:
            # These platforms require Playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
                page = ctx.new_page()
                page.set_default_timeout(20000) # Increased default timeout

                # Special handling for eVergabe 4.9 family if JS is heavily used
                if "kfw.vergabe.nrw.de" in url or "vergabemarktplatz.brandenburg.de" in url or \
                   "vergabe.muenchen.de" in url or "www.evergabe.bayern.de" in url or \
                   "ausschreibungen.kfw.de" in url:
                    try:
                        print(f"Navigating to {url} with Playwright (eVergabe 4.9 family)...")
                        page.goto(url, wait_until="load", timeout=30000)
                        
                        # Wait for Angular app to render, scroll down
                        page.wait_for_selector('body', state='attached')
                        page.mouse.wheel(0, 5000) # Scroll down aggressively
                        time.sleep(5) # Give it time to render after scroll

                        # Try to find "Alle herunterladen" button
                        download_all_btn_selectors = [
                            'button:has-text("Alle herunterladen")',
                            'button:has-text("Alle Dokumente herunterladen")',
                            'button:has-text("Alle Unterlagen")',
                            'button:has-text("Download All")',
                            'a:has-text("Alle herunterladen")',
                            'a:has-text("Alle Dokumente herunterladen")',
                            'div.btn-group button:has-text("Herunterladen")',
                            'span.mat-button-wrapper:has-text("Alle herunterladen")'
                        ]
                        
                        download_all_button = None
                        for selector in download_all_btn_selectors:
                            try:
                                btn = page.locator(selector).first
                                if btn.is_visible():
                                    download_all_button = btn
                                    break
                            except Exception:
                                pass

                        if not download_all_button:
                            print("No 'download all' button found immediately. Trying to click 'Vergabeunterlagen' tab.")
                            try:
                                # Look for "Vergabeunterlagen" tab or similar
                                tab_selectors = [
                                    'a.nav-link:has-text("Vergabeunterlagen")',
                                    'li.tab-link a:has-text("Vergabeunterlagen")',
                                    'button:has-text("Vergabeunterlagen")'
                                ]
                                for tab_selector in tab_selectors:
                                    tab = page.locator(tab_selector).first
                                    if tab.is_visible():
                                        tab.click(timeout=5000)
                                        page.wait_for_load_state('networkidle', timeout=10000)
                                        page.mouse.wheel(0, 5000) # Scroll again after tab click
                                        time.sleep(3) # Wait for content to render
                                        # Re-search for download button after tab click
                                        for selector in download_all_btn_selectors:
                                            try:
                                                btn = page.locator(selector).first
                                                if btn.is_visible():
                                                    download_all_button = btn
                                                    break
                                            except Exception:
                                                pass
                                        if download_all_button:
                                            break
                            except PlaywrightTimeoutError:
                                print(f"Could not find or click 'Vergabeunterlagen' tab for {url}")
                            except Exception as e:
                                print(f"Error clicking tab: {e}")

                        if download_all_button and download_all_button.is_visible():
                            print(f"Found and clicking 'Alle herunterladen' button for {url}...")
                            download_all_button.scroll_into_view_if_needed()
                            with page.expect_download(timeout=30000) as download_info:
                                download_all_button.click()
                                download = download_info.value
                                path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(path)
                                saved.append(str(Path(path).resolve()))
                                print(f"Downloaded ZIP: {download.suggested_filename}")
                            browser.close()
                            return {"downloaded_files": saved}
                        else:
                            print(f"No 'Alle herunterladen' found for eVergabe 4.9 family URL: {url}. Trying individual buttons if any.")
                            # Fallback to individual document downloads if "Alle Herunterladen" isn't found
                            # Look for links associated with "Dokument herunterladen" or similar
                            doc_download_links = page.locator('a:has-text("Dokument herunterladen"), button:has-text("Herunterladen"), a:has-text("Datei herunterladen")')
                            if doc_download_links.count() > 0:
                                print(f"Found {doc_download_links.count()} individual document download links.")
                                for i in range(doc_download_links.count()):
                                    link = doc_download_links.nth(i)
                                    try:
                                        link.scroll_into_view_if_needed()
                                        with page.expect_download(timeout=20000) as download_info:
                                            link.click()
                                            download = download_info.value
                                            path = os.path.join(output_dir, download.suggested_filename)
                                            download.save_as(path)
                                            saved.append(str(Path(path).resolve()))
                                            print(f"Downloaded individual file: {download.suggested_filename}")
                                        time.sleep(1) # Small delay between downloads
                                    except PlaywrightTimeoutError:
                                        print(f"Timeout downloading individual file.")
                                    except Exception as e:
                                        print(f"Error downloading individual file: {e}")
                            else:
                                print(f"No individual document download links found for {url}.")

                    except PlaywrightTimeoutError:
                        print(f"Timeout while processing eVergabe 4.9 family URL: {url}")
                    except Exception as e:
                        print(f"Error processing eVergabe 4.9 family URL {url}: {e}")
                    finally:
                        browser.close()
                    return {"downloaded_files": saved}

                # evergabe.de specific handling
                if "evergabe.de" in url and "unterlagen" not in url:
                    tender_id_match = re.search(r'(\d+)$', url)
                    if tender_id_match:
                        tender_id = tender_id_match.group(1)
                        documents_url = f"https://www.evergabe.de/unterlagen/{tender_id}"
                        print(f"Redirecting evergabe.de to documents URL: {documents_url}")
                        url = documents_url
                        
                print(f"Navigating to {url} with Playwright...")
                page.goto(url, wait_until="networkidle", timeout=30000)
                time.sleep(2) # Give JS a moment to render

                # Common Playwright ZIP/download all button detection for various platforms (evergabe.de, deutsche-evergabe, etc.)
                zip_selectors = [
                    'a[href*=".zip"]',
                    'a[href*="downloadall"]',
                    'a[href*="alleherunterladen"]',
                    'a[href*="alle-dokumente"]',
                    'a[href*="archive"]',
                    'a:has-text("alle herunterladen")',
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
                    'button:has-text("Alle herunterladen")',
                    'button:has-text("Download All")',
                    'a[onclick*="zip"], button[onclick*="zip"]', # For dynamic ZIP generation
                    # evergabe-online.de specific:
                    'a[href*="zipDownloadButton"]', 
                    # subreport.de specific:
                    'button.btn[onclick*="downloadDocument"]' # After clicking "anzeigen"
                ]

                downloaded_zip_or_all = False

                if "evergabe-online.de" in url:
                    # Specific to evergabe-online.de
                    print("Attempting to find zipDownloadButton for evergabe-online.de...")
                    zip_link_element = page.locator('a[href*="zipDownloadButton"]').first
                    if zip_link_element.is_visible():
                        zip_href = zip_link_element.get_attribute('href')
                        if zip_href:
                            zip_url = urljoin(url, html.unescape(zip_href))
                            print(f"Found evergabe-online.de zip link: {zip_url}")
                            try:
                                with page.expect_download(timeout=30000) as download_info:
                                    page.goto(zip_url, wait_until="load") # Directly navigating to the ZIP URL
                                    download = download_info.value
                                    path = os.path.join(output_dir, download.suggested_filename)
                                    download.save_as(path)
                                    saved.append(str(Path(path).resolve()))
                                    print(f"Downloaded evergabe-online.de ZIP: {download.suggested_filename}")
                                downloaded_zip_or_all = True
                            except PlaywrightTimeoutError:
                                print(f"Timeout downloading evergabe-online.de ZIP.")
                            except Exception as e:
                                print(f"Error downloading evergabe-online.de ZIP: {e}")

                elif "subreport.de" in url or "subreport-elvis.de" in url:
                    print("Processing subreport.de with Playwright...")
                    try:
                        # Click "anzeigen" to reveal documents
                        show_button = page.locator('button:has-text("anzeigen")').first
                        if show_button.is_visible():
                            show_button.click(timeout=5000)
                            page.wait_for_load_state('networkidle', timeout=10000)
                            time.sleep(5) # Wait for documents to load
                        else:
                            print("No 'anzeigen' button found, checking for docs directly.")

                        # Find the row containing "ZIP-Paket" or "Alle Dokumente" and click its download button
                        # This typically means finding a row and then a button within that row.
                        zip_row_selector = 'tr:has-text("ZIP-Paket"), tr:has-text("Alle Dokumente"), tr:has-text("Gesamtpaket")'
                        zip_row = page.locator(zip_row_selector).first
                        
                        if zip_row.is_visible():
                            download_button_in_row = zip_row.locator('button[onclick*="downloadDocument"], a:has-text("download")').first
                            if download_button_in_row.is_visible():
                                print("Found ZIP-Paket download button, clicking...")
                                with page.expect_download(timeout=30000) as download_info:
                                    download_button_in_row.click()
                                    download = download_info.value
                                    path = os.path.join(output_dir, download.suggested_filename)
                                    download.save_as(path)
                                    saved.append(str(Path(path).resolve()))
                                    print(f"Downloaded subreport ZIP: {download.suggested_filename}")
                                downloaded_zip_or_all = True
                            else:
                                print("Download button not found within ZIP-Paket row.")
                        else:
                            print("ZIP-Paket row not found on subreport page. Checking for other individual downloads.")

                        if not downloaded_zip_or_all:
                             # Fallback to individual downloads on subreport if no "download all" was found
                            all_download_buttons = page.locator('button[onclick*="downloadDocument"], a:has-text("download"), a:has-text("herunterladen")')
                            if all_download_buttons.count() > 0:
                                print(f"Found {all_download_buttons.count()} individual download buttons on subreport.")
                                for i in range(all_download_buttons.count()):
                                    btn = all_download_buttons.nth(i)
                                    try:
                                        if btn.is_visible() and "hidden" not in btn.get_attribute('class', default=''):
                                            print(f"Clicking individual download button {i+1} on subreport...")
                                            with page.expect_download(timeout=20000) as download_info:
                                                btn.click()
                                                download = download_info.value
                                                path = os.path.join(output_dir, download.suggested_filename)
                                                download.save_as(path)
                                                saved.append(str(Path(path).resolve()))
                                                print(f"Downloaded subreport individual file: {download.suggested_filename}")
                                            time.sleep(1) # Small delay
                                    except PlaywrightTimeoutError:
                                        print(f"Timeout downloading individual file from subreport.")
                                    except Exception as e:
                                        print(f"Error downloading individual file from subreport: {e}")

                    except PlaywrightTimeoutError:
                        print(f"Timeout while processing subreport.de URL: {url}")
                    except Exception as e:
                        print(f"Error processing subreport.de URL {url}: {e}")
                    finally:
                        browser.close()
                    return {"downloaded_files": saved}


                elif "deutsche-evergabe.de" in url or "bieterzugang.deutsche-evergabe.de" in url:
                    print("Processing deutsche-evergabe.de with Playwright...")
                    try:
                        page.goto(url, wait_until="load", timeout=30000)
                        page.wait_for_selector('body', state='attached') # Ensure body is loaded
                        time.sleep(5) # Wait for page to settle and JS to render

                        # Click the summary link to open the modal
                        bek_summary_link = page.locator('a.BekSummary').first
                        if bek_summary_link.count() > 0 and bek_summary_link.is_visible():
                            bek_summary_link.click(timeout=5000)
                            time.sleep(5) # Give modal time to load

                            current_url = page.url
                            uuid_match = re.search(r'/dashboards/dashboard_off/([0-9a-fA-F-]+)$', current_url)
                            if uuid_match:
                                uuid = uuid_match.group(1)
                                print(f"Extracted UUID for deutsche-evergabe.de: {uuid}")

                                # Fetch file list via JavaScript
                                file_data = page.evaluate('''(uuid) => {
                                    return new Promise((resolve, reject) => {
                                        fetch("/Verfahren/dxVUFilesForSupplier/" + uuid)
                                            .then(r => r.json())
                                            .then(data => resolve(data))
                                            .catch(e => reject(e));
                                    });
                                }''', uuid)
                                
                                if file_data and file_data.get('Files'):
                                    print(f"Found {len(file_data['Files'])} files to download for deutsche-evergabe.de.")
                                    base_download_url = "https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id="
                                    for file_info in file_data['Files']:
                                        doc_id = file_info.get('DokIDStr')
                                        file_name = file_info.get('DisplayName')
                                        if doc_id and file_name:
                                            download_link = f"{base_download_url}{doc_id}"
                                            print(f"Downloading deutsche-evergabe.de file: {file_name} from {download_link}")
                                            try:
                                                file_resp = requests.get(download_link, stream=True, timeout=10)
                                                file_resp.raise_for_status()
                                                save_file(file_resp, file_name, download_link)
                                            except requests.exceptions.RequestException as e:
                                                print(f"Error downloading deutsche-evergabe.de file {file_name}: {e}")
                            else:
                                print("Could not extract UUID from URL for deutsche-evergabe.de.")
                        else:
                            print("BekSummary link not found for deutsche-evergabe.de, cannot fetch documents.")
                    except PlaywrightTimeoutError:
                        print(f"Timeout while processing deutsche-evergabe.de URL: {url}")
                    except Exception as e:
                        print(f"Error processing deutsche-evergabe.de URL {url}: {e}")
                    finally:
                        browser.close()
                    return {"downloaded_files": saved}

                elif "bi-medien.de" in url or "deutsches-ausschreibungsblatt.de" in url:
                    print("Processing bi-medien.de with Playwright...")
                    try:
                        page.goto(url, wait_until="load", timeout=30000)
                        page.wait_for_selector('body', state='attached')
                        page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay
                        time.sleep(2)

                        # Find "Vergabeunterlagen" link, which likely opens in a new tab
                        vergabeunterlagen_link = page.locator('a:has-text("Vergabeunterlagen")').first
                        if vergabeunterlagen_link.count() > 0 and vergabeunterlagen_link.is_visible():
                            print("Found 'Vergabeunterlagen' link. Clicking to open new tab...")
                            with ctx.expect_page() as new_page_info:
                                vergabeunterlagen_link.click(timeout=5000)
                            new_page = new_page_info.value
                            new_page.wait_for_load_state('networkidle', timeout=20000)
                            new_page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay on new page
                            time.sleep(2)

                            zip_file_link = new_page.locator('a:has-text("Unterlagen als ZIP-Datei")').first
                            if zip_file_link.count() > 0 and zip_file_link.is_visible():
                                zip_href = zip_file_link.get_attribute('href')
                                if zip_href:
                                    full_zip_url = urljoin(new_page.url, zip_href)
                                    print(f"Found ZIP link on bi-medien: {full_zip_url}. Navigating directly to download.")
                                    # New context for direct download to avoid issues with current page state
                                    # or simply use requests if the URL is direct
                                    try:
                                        with new_page.expect_download(timeout=30000) as download_info:
                                            new_page.goto(full_zip_url, wait_until="load")
                                            download = download_info.value
                                            path = os.path.join(output_dir, download.suggested_filename)
                                            download.save_as(path)
                                            saved.append(str(Path(path).resolve()))
                                            print(f"Downloaded bi-medien ZIP: {download.suggested_filename}")
                                        downloaded_zip_or_all = True
                                    except PlaywrightTimeoutError:
                                        print(f"Timeout downloading bi-medien ZIP from {full_zip_url}.")
                                    except Exception as e:
                                        print(f"Error downloading bi-medien ZIP from {full_zip_url}: {e}")
                            else:
                                print("ZIP-FILE link 'Unterlagen als ZIP-Datei' not found on bi-medien sub-page.")
                            new_page.close()
                        else:
                            print("'Vergabeunterlagen' link not found on bi-medien main page.")
                    except PlaywrightTimeoutError:
                        print(f"Timeout while processing bi-medien.de URL: {url}")
                    except Exception as e:
                        print(f"Error processing bi-medien.de URL {url}: {e}")
                    finally:
                        browser.close()
                    return {"downloaded_files": saved}

                elif "vergabe24.de" in url or "bund.vergabe24.de" in url:
                    print("Processing vergabe24.de with Playwright...")
                    try:
                        page.goto(url, wait_until="load", timeout=30000)
                        page.wait_for_selector('body', state='attached')
                        time.sleep(3) # Wait for initial content

                        # Step 1: Click "Vergabeunterlagen anfordern"
                        try:
                            request_docs_btn = page.locator('button:has-text("Vergabeunterlagen anfordern")').first
                            if request_docs_btn.count() > 0 and request_docs_btn.is_visible():
                                request_docs_btn.click(timeout=5000)
                                page.wait_for_load_state('networkidle', timeout=10000)
                                time.sleep(2) # Wait for popup/next stage
                            else:
                                print("No 'Vergabeunterlagen anfordern' button found for vergabe24. Trying other ways.")
                                # Check for NetServer redirect here
                                if "NetServer" in page.url or "PublicationControllerServlet" in page.url:
                                    print(f"vergabe24.de redirected to NetServer. Re-processing with NetServer logic: {page.url}")
                                    browser.close() # Close current browser
                                    return scrape(page.url, output_dir) # Recursively call scrape for NetServer
                                
                        except PlaywrightTimeoutError:
                            print("Timeout clicking 'Vergabeunterlagen anfordern' on vergabe24.")
                            # Check for NetServer redirect here
                            if "NetServer" in page.url or "PublicationControllerServlet" in page.url:
                                print(f"vergabe24.de redirected to NetServer. Re-processing with NetServer logic: {page.url}")
                                browser.close() # Close current browser
                                return scrape(page.url, output_dir) # Recursively call scrape for NetServer

                        # Step 2: In popup, click "Unterlagen zur Ansicht herunterladen"
                        try:
                            view_docs_btn = page.locator('a:has-text("Unterlagen zur Ansicht herunterladen"), button:has-text("Unterlagen zur Ansicht herunterladen")').first
                            if view_docs_btn.count() > 0 and view_docs_btn.is_visible():
                                view_docs_btn.click(timeout=5000)
                                page.wait_for_load_state('networkidle', timeout=10000)
                                time.sleep(2) # Wait for form
                            else:
                                print("No 'Unterlagen zur Ansicht herunterladen' button found for vergabe24.")
                                # If it jumped directly to a page with download, handle it.
                        except PlaywrightTimeoutError:
                            print("Timeout clicking 'Unterlagen zur Ansicht herunterladen' on vergabe24.")

                        # Step 3: Click "Weiter"
                        try:
                            continue_btn = page.locator('button:has-text("Weiter")').first
                            if continue_btn.count() > 0 and continue_btn.is_visible():
                                continue_btn.click(timeout=5000)
                                page.wait_for_load_state('networkidle', timeout=10000)
                                time.sleep(2) # Wait for final download page
                            else:
                                print("No 'Weiter' button found for vergabe24.")
                        except PlaywrightTimeoutError:
                            print("Timeout clicking 'Weiter' on vergabe24.")

                        # Step 4: Capture download of "Vergabeunterlagen als ZIP-Datei herunterladen"
                        final_zip_btn = page.locator('a:has-text("Vergabeunterlagen als ZIP-Datei herunterladen")')
                        if final_zip_btn.count() > 0 and final_zip_btn.first.is_visible():
                            print("Found final ZIP download button on vergabe24. Clicking...")
                            with page.expect_download(timeout=30000) as download_info:
                                final_zip_btn.first.click()
                                download = download_info.value
                                path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(path)
                                saved.append(str(Path(path).resolve()))
                                print(f"Downloaded vergabe24 ZIP: {download.suggested_filename}")
                            downloaded_zip_or_all = True
                        else:
                            print("Final ZIP download button not found on vergabe24.")

                    except PlaywrightTimeoutError:
                        print(f"Timeout while processing vergabe24.de URL: {url}")
                    except Exception as e:
                        print(f"Error processing vergabe24.de URL {url}: {e}")
                    finally:
                        browser.close()
                    return {"downloaded_files": saved}

                elif ":f:/s/" in url and "sharepoint.com" in url:
                    print("Processing SharePoint URL with Playwright...")
                    try:
                        page.goto(url, wait_until="load", timeout=30000)
                        page.wait_for_selector('body', state='attached')
                        time.sleep(8) # Wait for React/Fluent UI to render
                        
                        download_button_selectors = [
                            'button[name="Download"]',
                            'button[data-automationid="downloadCommand"]',
                            'button:has-text("Download")',
                            'button:has-text("Herunterladen")'
                        ]
                        
                        download_button = None
                        for selector in download_button_selectors:
                            try:
                                btn = page.locator(selector).first
                                if btn.is_visible():
                                    download_button = btn
                                    break
                            except Exception:
                                pass
                        
                        if download_button:
                            print("Found SharePoint 'Download' button. Clicking...")
                            with page.expect_download(timeout=45000) as download_info: # Increased timeout for large SharePoint zips
                                download_button.click()
                                download = download_info.value
                                path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(path)
                                saved.append(str(Path(path).resolve()))
                                print(f"Downloaded SharePoint ZIP: {download.suggested_filename}")
                            downloaded_zip_or_all = True
                        else:
                            print("SharePoint 'Download' button not found.")
                    except PlaywrightTimeoutError:
                        print(f"Timeout while processing SharePoint URL: {url}")
                    except Exception as e:
                        print(f"Error processing SharePoint URL {url}: {e}")
                    finally:
                        browser.close()
                    return {"downloaded_files": saved}

                elif "eu.mu.ariba.com" in url:
                    print("Processing Ariba URL with Playwright...")
                    try:
                        page.goto(url, wait_until="load", timeout=30000)
                        page.wait_for_selector('body', state='attached')
                        time.sleep(5) # Wait for page to render

                        # Find "Download All" button
                        download_all_btn = page.locator('button:has-text("Download All"), button:has-text("Alle herunterladen")').first
                        if download_all_btn.count() > 0 and download_all_btn.is_visible():
                            print("Found Ariba 'Download All' button. Clicking...")
                            download_all_btn.scroll_into_view_if_needed()
                            with page.expect_download(timeout=60000) as download_info: # Ariba can be slow
                                download_all_btn.click()
                                download = download_info.value
                                path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(path)
                                saved.append(str(Path(path).resolve()))
                                print(f"Downloaded Ariba ZIP: {download.suggested_filename}")
                            downloaded_zip_or_all = True
                        else:
                            print("Ariba 'Download All' button not found.")
                    except PlaywrightTimeoutError:
                        print(f"Timeout while processing Ariba URL: {url}")
                    except Exception as e:
                        print(f"Error processing Ariba URL {url}: {e}")
                    finally:
                        browser.close()
                    return {"downloaded_files": saved}

                # General Playwright ZIP/download all attempts if not specific handler caught it
                if not downloaded_zip_or_all:
                    print(f"No specific handler or immediate 'download all' found for {url}. Trying generic Playwright ZIP selectors.")
                    for selector in zip_selectors:
                        try:
                            zip_button = page.locator(selector).first
                            if zip_button.is_visible():
                                print(f"Found potential ZIP/Download All button via selector: {selector}. Clicking...")
                                zip_button.scroll_into_view_if_needed()
                                with page.expect_download(timeout=30000) as download_info:
                                    zip_button.click()
                                    download = download_info.value
                                    path = os.path.join(output_dir, download.suggested_filename)
                                    download.save_as(path)
                                    saved.append(str(Path(path).resolve()))
                                    print(f"Downloaded generic ZIP: {download.suggested_filename}")
                                downloaded_zip_or_all = True
                                break
                        except PlaywrightTimeoutError:
                            print(f"Timeout clicking generic ZIP button with selector {selector}.")
                        except Exception as e:
                            print(f"Error trying generic ZIP button with selector {selector}: {e}")

                if not downloaded_zip_or_all:
                    print(f"No ZIP/Download All found using Playwright. Attempting individual file links for {url}.")
                    # Identify individual document links
                    document_links = []
                    # Try strong indicators first
                    for a_tag in page.locator('a[href]').all():
                        href = a_tag.get_attribute('href')
                        text = a_tag.text_content().strip().lower()
                        if href and (any(href.lower().endswith(ext) for ext in DOC_EXTS) or 
                                     "download" in text or "herunterladen" in text or "dokument" in text or "datei" in text):
                            document_links.append({"href": href, "text": text, "element": a_tag})

                    # Filter out navigation/login links heuristic
                    filtered_links = []
                    for link_info in document_links:
                        href = link_info['href']
                        text = link_info['text']
                        if not any(nav_word in text for nav_word in ["login", "startseite", "kontakt", "impressum"]) and \
                           not ("#" in href and text == "") and \
                           "javascript:void(0)" not in href and \
                           "mailto:" not in href and \
                           urlparse(href).netloc in (urlparse(url).netloc, ""): # Only same domain or relative
                            filtered_links.append(link_info)

                    for link_info in filtered_links:
                        try:
                            element = link_info['element']
                            # Ensure link is visible before clicking
                            if element.is_visible():
                                print(f"Clicking individual document link with text '{link_info['text']}' and href '{link_info['href']}'")
                                with page.expect_download(timeout=20000) as download_info:
                                    element.click()
                                    download = download_info.value
                                    path = os.path.join(output_dir, download.suggested_filename)
                                    download.save_as(path)
                                    saved.append(str(Path(path).resolve()))
                                    print(f"Downloaded individual file: {download.suggested_filename}")
                                time.sleep(1) # Small delay between downloads
                        except PlaywrightTimeoutError:
                            print(f"Timeout downloading individual file from {link_info['href']}")
                        except Exception as e:
                            print(f"Error downloading individual file from {link_info['href']}: {e}")

                browser.close()
                return {"downloaded_files": saved}
        
        elif "Satellite" in url or "VMPSatellite" in url:
            # DTVP (vergabeportal-bw.de and VMPSatellite/Satellite family)
            m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
            if m:
                project_id = m.group(1)
                prefix = "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"
                parts = urlparse(url)
                # Note: The provided pattern is wrong sometimes. It should be .../documents/zip/ rather than /archive/
                # Let's try both common patterns.
                zip_url_candidate1 = f"{parts.scheme}://{parts.netloc}/{prefix}/public/company/project/{project_id}/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
                zip_url_candidate2 = f"{parts.scheme}://{parts.netloc}/{prefix}/public/company/project/{project_id}/de/documents/zip/{project_id}.zip" # More common for newer DTVP
                
                print(f"Trying DTVP ZIP URL Candidate 1: {zip_url_candidate1}")
                try:
                    response = requests.get(zip_url_candidate1, stream=True, timeout=10)
                    response.raise_for_status()
                    if 'application/zip' in response.headers.get('Content-Type', '').lower():
                        filename = response.headers.get("Content-Disposition", f"Vergabeunterlagen_{project_id}.zip").split("filename=")[-1].strip('"\'')
                        save_file(response, filename, zip_url_candidate1)
                        return {"downloaded_files": saved}
                    else:
                        print(f"Candidate 1 was not a zip for {url}. Status: {response.status_code}, Content-Type: {response.headers.get('Content-Type')}")
                except requests.exceptions.RequestException as e:
                    print(f"Failed to download DTVP ZIP candidate 1: {e}")

                print(f"Trying DTVP ZIP URL Candidate 2: {zip_url_candidate2}")
                try:
                    response = requests.get(zip_url_candidate2, stream=True, timeout=10)
                    response.raise_for_status()
                    if 'application/zip' in response.headers.get('Content-Type', '').lower():
                        filename = response.headers.get("Content-Disposition", f"{project_id}.zip").split("filename=")[-1].strip('"\'')
                        save_file(response, filename, zip_url_candidate2)
                        return {"downloaded_files": saved}
                    else:
                        print(f"Candidate 2 was not a zip for {url}. Status: {response.status_code}, Content-Type: {response.headers.get('Content-Type')}")
                except requests.exceptions.RequestException as e:
                    print(f"Failed to download DTVP ZIP candidate 2: {e}")
            else:
                print(f"Could not extract project ID from DTVP URL: {url}")
            return {"downloaded_files": saved} # If DTVP zip fails, no fallback for individual files as it's typically a direct link.


        else:
            # Generic approach for non-JS static pages using requests
            print(f"Attempting generic requests-based scrape for {url}...")
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.content, 'html.parser')

            # PRIORITY RULE: Try to find a single "download all" or ZIP URL
            zip_links = []
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                text = a_tag.get_text(strip=True).lower()
                
                # Rule 1: href ends with .zip or contains keywords
                if href.lower().endswith(".zip") or \
                   any(keyword in href.lower() for keyword in ["downloadall", "alleherunterladen", "alle-dokumente", "archive"]) :
                    zip_links.append({"url": urljoin(url, href), "type": "href_pattern"})
                # Rule 2: visible text contains keywords
                elif any(keyword in text for keyword in ["alle herunterladen", "alle dokumente", "alle als zip", "alles herunterladen",
                                                      "download all", "download zip", "zip herunterladen", "unterlagen herunterladen",
                                                      "alle unterlagen", "gesamtpaket", "vergabeunterlagen herunterladen"]):
                    zip_links.append({"url": urljoin(url, href), "type": "text_pattern"})
                # Rule 3: onclick constructs a ZIP download URL (simple check)
                elif a_tag.has_attr('onclick') and any(keyword in a_tag['onclick'].lower() for keyword in ["zip", "download", "herunterladen"]):
                    # This is difficult to parse reliably without JS execution.
                    # Best effort: if it's an onclick, assume it triggers a download
                    # and try the href if present, or punt to Playwright if no href.
                    if href and href != "#" and "javascript:void(0)" not in href:
                         zip_links.append({"url": urljoin(url, href), "type": "onclick_pattern"})

            if zip_links:
                # Prioritize zip_links by type. For simplicity, just try the first one found.
                # A more robust solution might try all or filter by preference.
                print(f"Found potential ZIP/Download All link: {zip_links[0]['url']} (Reason: {zip_links[0]['type']}). Attempting download.")
                try:
                    response = requests.get(zip_links[0]['url'], stream=True, timeout=20)
                    response.raise_for_status()
                    # Check Content-Type to ensure it's actually a document/zip
                    content_type = response.headers.get('Content-Type', '').lower()
                    content_disp = response.headers.get('Content-Disposition', '').lower()

                    if 'application/zip' in content_type or \
                       'application/octet-stream' in content_type and ('.zip' in content_disp or zip_links[0]['url'].lower().endswith('.zip')):
                        filename = content_disp.split("filename=")[-1].strip('"\'') if "filename=" in content_disp else Path(zip_links[0]['url']).name
                        if not filename: filename = "downloaded_archive.zip"
                        save_file(response, filename, zip_links[0]['url'])
                        return {"downloaded_files": saved}
                    else:
                        print(f"Link {zip_links[0]['url']} did not return a valid ZIP (Content-Type: {content_type}). Falling back to individual files.")
                except requests.exceptions.RequestException as e:
                    print(f"Failed to download ZIP from {zip_links[0]['url']}: {e}. Falling back to individual files.")

            # If no "download all" option, download individual files
            print("No 'download all' found. Looking for individual file links.")
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                text = a_tag.get_text(strip=True).lower()
                full_url = urljoin(url, href)
                parsed_href = urlparse(full_url)
                
                # Check for document extensions and ignore common non-document links
                if any(parsed_href.path.lower().endswith(ext) for ext in DOC_EXTS) and \
                   not any(exclusion in text for exclusion in ["login", "startseite", "kontakt", "impressum", "agb"]) and \
                   not any(exclusion in href for exclusion in ["mailto:", "tel:", "#", "javascript:void(0)"]):
                    
                    # Basic deduplication by URL
                    if full_url in [s['url'] for s in saved]:
                        continue # Already added
                    
                    filename = Path(parsed_href.path).name
                    if not filename: # If path doesn't yield a name, check query parameters
                         query_params = parse_qs(parsed_href.query)
                         filename_param = query_params.get("filename") or query_params.get("name")
                         if filename_param: filename = filename_param[0]
                    if not filename:
                         filename = f"document_{hashlib.md5(full_url.encode()).hexdigest()}{Path(parsed_href.path).suffix or '.bin'}"

                    try:
                        print(f"Downloading individual file: {full_url}")
                        file_resp = requests.get(full_url, stream=True, timeout=10)
                        file_resp.raise_for_status()
                        save_file(file_resp, filename, full_url)
                    except requests.exceptions.RequestException as e:
                        print(f"Failed to download individual file {full_url}: {e}")

    except PlaywrightTimeoutError as e:
        print(f"Playwright timed out: {e}")
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")

    return {"downloaded_files": saved}

from bs4 import BeautifulSoup