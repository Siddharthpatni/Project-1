import os, re, requests, hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright

DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xml", ".xls", ".xlsx",
            ".ods", ".odt", ".gaeb", ".x81", ".x83", ".ppt", ".pptx", ".txt"}

def download_file(session, url, output_dir, saved):
    if not url:
        return
    
    # Basic check to avoid re-downloading
    filename = url.split('/')[-1].split('?')[0]
    if not any(filename.endswith(ext) for ext in DOC_EXTS) and ".zip" not in filename:
        # Try to infer extension if not present
        r = session.head(url, allow_redirects=True, timeout=10)
        content_type = r.headers.get('Content-Type', '').lower()
        if 'pdf' in content_type:
            filename += '.pdf'
        elif 'zip' in content_type:
            filename += '.zip'
        elif 'excel' in content_type or 'spreadsheetml' in content_type:
            filename += '.xlsx'
        elif 'word' in content_type or 'document' in content_type:
            filename += '.docx'
        elif 'xml' in content_type:
            filename += '.xml'
        elif 'powerpoint' in content_type or 'presentation' in content_type:
            filename += '.pptx'
        elif 'text/plain' in content_type:
            filename += '.txt'

    if not any(filename.endswith(ext) for ext in DOC_EXTS) and ".zip" not in filename:
        # If still no valid extension, skip
        return

    filepath = os.path.join(output_dir, filename)
    if not os.path.exists(filepath):
        try:
            r = session.get(url, stream=True, timeout=20)
            r.raise_for_status()
            with open(filepath, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            saved.append(filepath)
        except requests.exceptions.RequestException as e:
            print(f"Error downloading {url}: {e}")
            pass

def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    
    # Use requests for direct downloads and initial page fetching if no JS is needed
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
    })

    try:
        # Check for DTVP pattern first (pure URL manipulation)
        if "/Satellite/" in url or "/VMPSatellite/" in url:
            m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
            if m:
                project_id = m.group(1)
                prefix = "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"
                parts = urlparse(url)
                dtvp_zip_url = f"{parts.scheme}://{parts.netloc}/{prefix}/public/company/project/{project_id}/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
                download_file(session, dtvp_zip_url, output_dir, saved)
                if saved:  # If ZIP was found and downloaded, we are done
                    return {"downloaded_files": saved}

        # lubey.de specific logic (HTML parsing, no Playwright needed for this structure)
        if "www.lubey.de" in url:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            
            # Prefer ZIP download
            zip_match = re.search(r'<a href="(https://www\.lubey\.de/alloc/[^/]+/all_documents)"', response.text)
            if zip_match:
                zip_url = zip_match.group(1)
                download_file(session, zip_url, output_dir, saved)
                if saved:
                    return {"downloaded_files": saved}

            # If no ZIP, download individual PDFs
            pdf_links = re.findall(r'<a href="(https://www\.lubey\.de/alloc/[^"]+)"[^>]*?><i class="fas fa-file-pdf fa-fw"></i>', response.text)
            for link in pdf_links:
                download_file(session, link, output_dir, saved)

        # NetServer family: vergabe.autobahn.de, tender24.de etc.
        elif "/NetServer/" in url or "/PublicationControllerServlet?" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)

                # Prioritize "download all" / ZIP
                zip_link = page.locator('a[href*=".zip" i], a:has-text("download all"i), a:has-text("alle herunterladen"i), a:has-text("alle dokumente"i), a:has-text("alle als zip"i), a:has-text("alles herunterladen"i), a:has-text("download zip"i), a:has-text("zip herunterladen"i), a:has-text("unterlagen herunterladen"i), a:has-text("alle unterlagen"i), a:has-text("gesamtpaket"i), a:has-text("vergabeunterlagen herunterladen"i)')
                if zip_link.count() > 0:
                    with page.expect_download() as download_info:
                        zip_link.first.click()
                    download = download_info.value
                    file_path = os.path.join(output_dir, download.suggested_filename)
                    download.save_as(file_path)
                    saved.append(file_path)
                    browser.close()
                    return {"downloaded_files": saved}
                
                # Check for NetServer specific function=_DownloadTenderDocuments
                if "function=_Details" in url or "function=Detail" in url:
                    tender_oid_match = re.search(r"[?&]TenderOID=([^&]+)", url)
                    if tender_oid_match:
                        tender_oid = tender_oid_match.group(1)
                        parsed_url = urlparse(url)
                        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}{'/'.join(parsed_url.path.split('/')[:-1])}"
                        netserver_zip_url = f"{base_url}/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={tender_oid}"
                        
                        # Look for additional params in hidden fields
                        hidden_fields_str = ""
                        # This works for a specific structure, may need refinement for others
                        for input_tag in page.locator('input[type="hidden"]').all():
                            name = input_tag.get_attribute('name')
                            value = input_tag.get_attribute('value')
                            if name and value and name not in ['TenderOID', '__RequestVerificationToken']: # Avoid duplicates
                                hidden_fields_str += f"&{name}={value}"

                        if hidden_fields_str:
                             netserver_zip_url += hidden_fields_str

                        # NetServer ZIP doesn't need validation, just download
                        request_context = page.context.request
                        download_response = request_context.get(netserver_zip_url)
                        if download_response.status == 200:
                            content_disposition = download_response.headers.get("Content-Disposition")
                            filename = re.findall("filename\*?=(?:UTF-8'')?\"?([^\"'>]+)\"?", content_disposition)[0] if content_disposition else "download.zip"
                            file_path = os.path.join(output_dir, filename)
                            with open(file_path, "wb") as f:
                                f.write(download_response.body())
                            saved.append(file_path)
                            browser.close()
                            return {"downloaded_files": saved}
                    
                # If no "download all" found, download individual documents with function=_DownloadDocument
                doc_links = page.locator('a[href*="function=_DownloadDocument"]').all()
                for link in doc_links:
                    href = link.get_attribute('href')
                    if href:
                        abs_url = urljoin(page.url, href)
                        with page.expect_download() as download_info:
                            link.click()
                        download = download_info.value
                        file_path = os.path.join(output_dir, download.suggested_filename)
                        download.save_as(file_path)
                        saved.append(file_path)
                browser.close()


        # evergabe.de
        elif "www.evergabe.de" in url:
            tender_id_match = re.search(r'/(\d+)$', url)
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
                    page.goto(docs_url, wait_until="networkidle", timeout=20000)
                    page.wait_for_timeout(5000) # Wait for JS rendering

                    all_doc_links = page.locator('a:has-text("Datei herunterladen")').all()
                    for link in all_doc_links:
                        href = link.get_attribute('href')
                        if href:
                            abs_url = urljoin(page.url, href)
                            try:
                                with page.expect_download() as download_info:
                                    link.click() # This sometimes works better than direct requests for JS sites
                                download = download_info.value
                                file_path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(file_path)
                                saved.append(file_path)
                            except Exception as dl_e:
                                print(f"Playwright download failed for {abs_url}: {dl_e}. Trying requests...")
                                download_file(session, abs_url, output_dir, saved) # Fallback to requests
                    browser.close()
            else:
                print("Could not extract tender ID for evergabe.de")

        # eVergabe 4.9 / Cosinex family
        elif any(domain in url for domain in ["kfw.vergabe.nrw.de", "vergabemarktplatz.brandenburg.de", "vergabe.muenchen.de", "bieterportal.noncd.db.de", "www.evergabe.bayern.de", "ausschreibungen.kfw.de"]) or "eVergabe" in url or "Angular" in page.content(): # Simplified check for Angular (not perfect)
             with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="load", timeout=20000)
                page.wait_for_timeout(8000) # Give Angular time to render

                # Try to click "Alle herunterladen" button
                zip_button = page.locator('button:has-text("Alle herunterladen")')
                if zip_button.count() > 0:
                    zip_button.scroll_into_view_if_needed()
                    with page.expect_download() as dl:
                        zip_button.click(timeout=5000) # Add timeout for click
                    download = dl.value
                    file_path = os.path.join(output_dir, download.suggested_filename)
                    download.save_as(file_path)
                    saved.append(file_path)
                else:
                    # Try clicking tabs if "Alle herunterladen" is not immediately visible
                    for tab_text in ["Teilnehmen", "Vergabeunterlagen", "Dokumente"]:
                        tab = page.locator(f'button:has-text("{tab_text}")')
                        if tab.count() > 0 and not tab.get_attribute("aria-selected") == "true":
                            tab.click()
                            page.wait_for_timeout(3000) # Wait for tab content to load
                            # Try again to find the download button
                            zip_button = page.locator('button:has-text("Alle herunterladen")')
                            if zip_button.count() > 0:
                                zip_button.scroll_into_view_if_needed()
                                with page.expect_download() as dl:
                                    zip_button.click(timeout=5000)
                                download = dl.value
                                file_path = os.path.join(output_dir, download.suggested_filename)
                                download.save_as(file_path)
                                saved.append(file_path)
                                break # Found and downloaded, exit loop

                browser.close()

        # evergabe-online.de (Apache Wicket)
        elif "evergabe-online.de" in url:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            
            import html
            zip_url_found = None
            for link_match in re.finditer(r'<a[^>]+href="([^"]*zipDownloadButton[^"]*)"', response.text):
                href = link_match.group(1)
                # Filter out specific unwanted links if any
                if "archivedProcedures.html" not in href and "login.html" not in href:
                    zip_url_found = urljoin(url, html.unescape(href))
                    break
            
            if zip_url_found:
                download_file(session, zip_url_found, output_dir, saved)

        # subreport.de and subreport-elvis.de
        elif "subreport.de" in url or "subreport-elvis.de" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                
                # Click "anzeigen" button to reveal documents
                anzeigen_button = page.locator('button:has-text("anzeigen")')
                if anzeigen_button.count() > 0:
                    anzeigen_button.click()
                    page.wait_for_timeout(5000) # Give time for content to load

                # Find ZIP-Paket download button
                zip_row = page.locator('tr:has-text("ZIP-Paket"), tr:has-text("Alle Dokumente")').first
                if zip_row.count() > 0:
                    download_button = zip_row.locator('button:has-text("download")')
                    if download_button.count() > 0:
                        with page.expect_download() as dl:
                            download_button.click()
                        download = dl.value
                        file_path = os.path.join(output_dir, download.suggested_filename)
                        download.save_as(file_path)
                        saved.append(file_path)
                
                browser.close()

        # deutsche-evergabe.de
        elif "deutsche-evergabe.de" in url or "bieterzugang.deutsche-evergabe.de" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="load", timeout=20000)
                page.wait_for_timeout(5000)

                # Click a.BekSummary to open modal
                bek_summary = page.locator('a.BekSummary').first
                if bek_summary.count() > 0:
                    bek_summary.click()
                    page.wait_for_timeout(5000) # Wait for modal

                    # Extract UUID from current URL (likely opened a new URL in modal)
                    current_url = page.url
                    uuid_match = re.search(r'/dashboards/dashboard_off/([a-f0-9-]+)$', current_url, re.IGNORECASE)
                    if uuid_match:
                        uuid = uuid_match.group(1)
                        # Fetch file data via JS
                        file_data = page.evaluate('''(uuid) => {
                            return new Promise((resolve) => {
                                fetch("/Verfahren/dxVUFilesForSupplier/" + uuid)
                                    .then(r => r.json()).then(data => resolve(data));
                            });
                        }''', uuid)
                        
                        if file_data and 'Dokumente' in file_data:
                            for doc in file_data['Dokumente']:
                                dok_id_str = doc.get('DokIDStr')
                                if dok_id_str:
                                    download_url = f"https://addon-service.deutsche-evergabe.de/home/DirectDocload/?o=t0KsgIFkMoE%3d&id={dok_id_str}"
                                    download_file(session, download_url, output_dir, saved)
                browser.close()

        # bi-medien.de
        elif "bi-medien.de" in url or "deutsches-ausschreibungsblatt.de" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay

                # Look for "Vergabeunterlagen" which opens in a new tab
                vergabeunterlagen_link = page.locator('a:has-text("Vergabeunterlagen")').first
                if vergabeunterlagen_link.count() > 0:
                    with ctx.expect_page() as new_page_info:
                        vergabeunterlagen_link.click()
                    new_page = new_page_info.value
                    new_page.wait_for_load_state("domcontentloaded")
                    new_page.evaluate('document.querySelector("#cmpwrapper")?.remove()') # Remove cookie overlay on new page

                    zip_link = new_page.locator('a:has-text("Unterlagen als ZIP-Datei")').first
                    if zip_link.count() > 0:
                        href = zip_link.get_attribute('href')
                        if href:
                            abs_url = urljoin(new_page.url, href)
                            download_file(session, abs_url, output_dir, saved)
                    new_page.close()
                browser.close()

        # vergabe24.de / bund.vergabe24.de
        elif "vergabe24.de" in url:
            # Check for NetServer redirect first
            response = session.get(url, allow_redirects=True, timeout=10)
            if "/NetServer/" in response.url or "/PublicationControllerServlet?" in response.url:
                # Re-run scraper for NetServer URL
                return scrape(response.url, output_dir)

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="load", timeout=20000)
                
                # Click "Vergabeunterlagen anfordern"
                page.locator('a:has-text("Vergabeunterlagen anfordern")').first.click()
                page.wait_for_selector('button:has-text("Unterlagen zur Ansicht herunterladen")') 
                
                # Click "Unterlagen zur Ansicht herunterladen"
                page.locator('button:has-text("Unterlagen zur Ansicht herunterladen")').click()
                page.wait_for_selector('button:has-text("Weiter")')
                
                # Click "Weiter"
                page.locator('button:has-text("Weiter")').click()
                page.wait_for_selector('a:has-text("Vergabeunterlagen als ZIP-Datei herunterladen")')

                zip_link = page.locator('a:has-text("Vergabeunterlagen als ZIP-Datei herunterladen")').first
                if zip_link.count() > 0:
                    with page.expect_download() as dl:
                        zip_link.click()
                    download = dl.value
                    file_path = os.path.join(output_dir, download.suggested_filename)
                    download.save_as(file_path)
                    saved.append(file_path)
                browser.close()

        # SharePoint (:f: folder sharing links)
        elif ".sharepoint.com/:f:/" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="load", timeout=20000)
                page.wait_for_timeout(10000) # Give React/Fluent UI time to render

                download_button = page.locator('button[name="Download"], [data-automationid="downloadCommand"]').first
                if download_button.count() > 0:
                    with page.expect_download() as dl:
                        download_button.click()
                    download = dl.value
                    file_path = os.path.join(output_dir, download.suggested_filename)
                    download.save_as(file_path)
                    saved.append(file_path)
                browser.close()

        # Ariba
        elif "eu.mu.ariba.com" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                page.goto(url, wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(8000)

                # Scroll to "Tender Documents" section (might need element-specific scrolling)
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')

                download_all_button = page.locator('a:has-text("Download All"), a:has-text("Alle Herunterladen")').first
                if download_all_button.count() > 0:
                    with page.expect_download() as dl:
                        download_all_button.click()
                    download = dl.value
                    file_path = os.path.join(output_dir, download.suggested_filename)
                    download.save_as(file_path)
                    saved.append(file_path)
                browser.close()

        # General case (if no specific platform detected or Playwright not needed)
        else:
            response = session.get(url, timeout=15)
            response.raise_for_status()

            # Find ZIP links first
            zip_links_raw = re.findall(r'href="([^"]*\.zip)"', response.text, re.IGNORECASE)
            zip_links_text = re.findall(r'<a[^>]*>(.*?alle herunterladen|.*?alle dokumente|.*?alle als zip|.*?alles herunterladen|.*?download all|.*?download zip|.*?zip herunterladen|.*?unterlagen herunterladen|.*?alle unterlagen|.*?gesamtpaket|.*?vergabeunterlagen herunterladen.*?)</a>', response.text, re.IGNORECASE | re.DOTALL)
            
            # Extract hrefs from text-based zip links if they exist
            zip_links_from_text = []
            for text_match in zip_links_text:
                a_tag_match = re.search(r'href="([^"]+)"', text_match)
                if a_tag_match:
                    zip_links_from_text.append(urljoin(url, a_tag_match.group(1)))
            
            all_zip_links = list(set(zip_links_raw + zip_links_from_text)) # Remove duplicates

            if all_zip_links:
                for zip_link in all_zip_links:
                    download_file(session, urljoin(url, zip_link), output_dir, saved)
                if saved: # If any ZIP downloaded successfully, we're done
                    return {"downloaded_files": saved}

            # If no ZIP, look for individual documents based on extensions
            doc_links = re.findall(r'href="([^"]+?(?:\.pdf|\.doc|\.docx|\.xls|\.xlsx|\.ppt|\.pptx|\.rar|\.7z|\.txt|\.odt|\.ods|\.gaeb|\.x81|\.x83))(?:\?[^"]*)?"', response.text, re.IGNORECASE)
            for link in doc_links:
                # Basic filter for common undesired links (navigation, login, etc. - can be expanded)
                if not any(keyword in link.lower() for keyword in ["login", "register", "extern", "javascript:void(0)"]):
                    download_file(session, urljoin(url, link), output_dir, saved)

    except Exception as e:
        print(f"An error occurred during scraping: {e}")
        # Clean up browser if open on error
        try:
            if 'browser' in locals() and browser:
                browser.close()
        except:
            pass

    return {"downloaded_files": saved}