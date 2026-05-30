import os
import re
import requests
import hashlib
import html
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xml", ".xls", ".xlsx",
            ".ods", ".odt", ".gaeb", ".x81", ".x83", ".ppt", ".pptx",
            ".txt", ".rar", ".7z"}

def download_file(url, output_dir, session=None):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        if session:
            response = session.get(url, stream=True, timeout=15, headers=headers)
        else:
            response = requests.get(url, stream=True, timeout=15, headers=headers)

        response.raise_for_status()

        content_type = response.headers.get('content-type', '').lower()
        if 'html' in content_type or 'text' in content_type:
            return None

        filename = Path(urlparse(url).path).name
        if not filename:
            # Try to get filename from Content-Disposition header
            cd = response.headers.get('content-disposition')
            if cd:
                fname = re.findall('filename="?(.+)"?', cd)
                if fname:
                    filename = fname[0]
        
        if not filename: # Fallback if no filename found
            filename = hashlib.md5(url.encode()).hexdigest() + ".bin"

        filepath = os.path.join(output_dir, filename)
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return filepath
    except Exception as e:
        print(f"Failed to download {url}: {e}")
        return None

def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    
    try:
        # NetServer Family (vergabe.autobahn.de, tender24.de, etc.)
        if "NetServer" in url:
            base_url = urlparse(url)._replace(query=None).geturl()
            
            # Try to find TenderOID from the initial URL
            oid_match = re.search(r"TenderOID=([^&]+)", url)
            if oid_match:
                tender_oid = oid_match.group(1)
                
                # Construct the direct ZIP download URL
                zip_download_url = f"{base_url.split('/NetServer/')[0]}/NetServer/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={tender_oid}"
                
                # NetServer sometimes requires hidden form fields captured from the Detail page.
                # Let's use Playwright to get these if available, otherwise try direct download.
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        ctx = browser.new_context(
                            accept_downloads=True, locale="de-DE",
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        )
                        page = ctx.new_page()
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        
                        # Look for hidden inputs that might be needed for download
                        hidden_params = {}
                        for field in page.locator("input[type='hidden']").all():
                            name = field.get_attribute("name")
                            value = field.get_attribute("value")
                            if name and value:
                                hidden_params[name] = value

                        if oid_match := re.search(r"TenderOID=([^&]+)", url):
                           tender_oid = oid_match.group(1)
                           
                           download_url_parts = []
                           base_download_url_path = urlparse(url)._replace(query=None).geturl() # Base path for download URL

                           # This part is tricky as the exact download URL structure can vary
                           # We aim for the _DownloadTenderDocuments function
                           potential_zip_url = f"{url.split('/NetServer/')[0]}/NetServer/TenderingProcedureDetails?function=_DownloadTenderDocuments&TenderOID={tender_oid}"

                           if hidden_params:
                               # Add any captured hidden parameters to the download URL
                               for key, val in hidden_params.items():
                                   # Avoid adding TenderOID again if already present
                                   if key.lower() != 'tendoroid' and key.lower() != 'tenderoid':
                                       potential_zip_url += f"&{key}={val}"
                           
                           # Try downloading the constructed ZIP URL directly
                           downloaded_path = download_file(potential_zip_url, output_dir)
                           if downloaded_path:
                               saved.append(os.path.abspath(downloaded_path))
                               return {"downloaded_files": saved} # Prioritize ZIP

                        # If no ZIP found or direct download failed, look for individual files
                        individual_links = page.locator("a[href*='function=_DownloadDocument']").all()
                        for link in individual_links:
                            href = link.get_attribute("href")
                            if href:
                                doc_url = urljoin(base_url, href)
                                downloaded_path = download_file(doc_url, output_dir)
                                if downloaded_path:
                                    saved.append(os.path.abspath(downloaded_path))
                        
                        browser.close()
                        return {"downloaded_files": saved}

                except PlaywrightTimeoutError:
                    print(f"Playwright timed out for {url}")
                except Exception as e:
                    print(f"Playwright error for NetServer: {e}")
                    # Fallback to a simpler requests-based approach if Playwright fails
                    pass

            # Fallback: If no OID found or Playwright fails, try direct download of ZIP, then individual files with requests
            session = requests.Session()
            response = session.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try to find a direct ZIP download link
            zip_url = None
            for a in soup.find_all('a', href=True):
                href = a['href']
                if any(keyword in href.lower() for keyword in ['downloadall', 'alleherunterladen', 'alle-dokumente', 'archive', '.zip', '.rar', '.7z']):
                    zip_url = urljoin(url, href)
                    break
            
            if zip_url:
                downloaded_path = download_file(zip_url, output_dir, session)
                if downloaded_path:
                    saved.append(os.path.abspath(downloaded_path))
                    return {"downloaded_files": saved}

            # If no ZIP found, look for individual file links
            for a in soup.find_all('a', href=True):
                href = a['href']
                parsed_href = urlparse(href)
                ext = Path(parsed_href.path).suffix.lower()
                if ext in DOC_EXTS:
                    doc_url = urljoin(url, href)
                    downloaded_path = download_file(doc_url, output_dir, session)
                    if downloaded_path:
                        saved.append(os.path.abspath(downloaded_path))

        # eVergabe 4.9 / Cosinex family (kfw.vergabe.nrw.de, vergabemarktplatz.brandenburg.de, etc.)
        elif "eVergabe" in url or "Cosinex" in url or "vergabemarktplatz" in url or "cosinex" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads=True, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="networkidle", timeout=30000) # networkidle for dynamic content
                    page.wait_for_load_state("networkidle")
                    page.evaluate('window.scrollTo(0, document.body.scrollHeight)') # Scroll to ensure all elements load

                    # Look for "Alle herunterladen" button first
                    download_all_button = page.locator("button:has-text('Alle herunterladen'), button:has-text('Alle Dokumente herunterladen'), a.btn:has-text('Alle herunterladen')")
                    if download_all_button.count() > 0:
                        btn = download_all_button.first
                        btn.scroll_into_view_if_needed()
                        with page.expect_download() as dl:
                            btn.click()
                        download = dl.value
                        filename = download.suggested_filename
                        filepath = os.path.join(output_dir, filename)
                        download.save_as(filepath)
                        saved.append(os.path.abspath(filepath))
                        browser.close()
                        return {"downloaded_files": saved}

                    # If no "Alle herunterladen", look for individual file links
                    # Try clicking tabs first if they exist
                    tender_docs_tab = page.locator("a:has-text('Vergabeunterlagen'), a:has-text('Dokumente')").first
                    if tender_docs_tab.count() > 0 and tender_docs_tab.is_visible():
                        href = tender_docs_tab.get_attribute('href')
                        if href:
                            # This might open a new page or load content dynamically
                            # For simplicity, let's assume it loads in the same page or redirects
                            # In a real scenario, you might need context.pages[1] or page.wait_for_url
                            try:
                                with page.expect_popup() as popup_info:
                                     tender_docs_tab.click()
                                page = popup_info.value
                                page.wait_for_load_state("networkidle")
                            except PlaywrightTimeoutError:
                                # If no popup, assume content loads in the same page
                                tender_docs_tab.click()
                                page.wait_for_load_state("networkidle")
                                


                    # After potentially clicking a tab, re-evaluate for links
                    links = page.locator("a[href]").all()
                    for link in links:
                        href = link.get_attribute('href')
                        text = link.inner_text().lower()
                        if href and any(href.lower().endswith(ext) for ext in DOC_EXTS) and not any(nav in text for nav in ["zurück", "zur übersicht", "detail", "zurück zur übersicht"]):
                             if not (href.startswith("javascript:") or href.startswith("#")):
                                doc_url = urljoin(url, href)
                                downloaded_path = download_file(doc_url, output_dir)
                                if downloaded_path:
                                    saved.append(os.path.abspath(downloaded_path))

                except PlaywrightTimeoutError:
                    print(f"Playwright timed out for {url} on eVergabe site")
                except Exception as e:
                    print(f"Playwright error on eVergabe site for {url}: {e}")
                finally:
                    browser.close()
            return {"downloaded_files": saved}
            
        # SharePoint links
        elif ".sharepoint.com/:f:/" in url:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                ctx = browser.new_context(
                    accept_downloads={"behavior": "allow"}, locale="de-DE",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=25000)
                    # Attempt to remove cookie banners
                    try:
                        page.evaluate('document.querySelector("[aria-label=\'Accept all cookies\']")?.click()')
                        page.evaluate('document.querySelector("#cmpwrapper")?.remove()')
                        page.evaluate('document.querySelector("#cookieConsent")?.remove()')
                        page.wait_for_timeout(2000) # Give it a moment to disappear
                    except Exception:
                        pass # Ignore errors if banners are not present or cannot be removed

                    # Wait for specific SharePoint elements to appear
                    page.wait_for_selector('button[name="Download"]', timeout=15000)
                    
                    # Find the download button for the entire folder
                    download_button = page.locator('button[name="Download"], [data-automationid="downloadCommand"]').first
                    if download_button.count() > 0:
                        with page.expect_download() as dl:
                            if download_button.is_visible():
                                download_button.click()
                            else:
                                # Sometimes it's not directly clickable, might need JS execution
                                page.evaluate('document.querySelector(\'button[name="Download"], [data-automationid="downloadCommand"]\').click()')
                        
                        download = dl.value
                        # SharePoint often zips everything into a folder structure
                        # We'll save the zip, but might need to extract later if that's the goal.
                        # For now, assume saving the zip is sufficient.
                        filename = download.suggested_filename
                        filepath = os.path.join(output_dir, filename)
                        download.save_as(filepath)
                        saved.append(os.path.abspath(filepath))
                        return {"downloaded_files": saved}
                    
                except PlaywrightTimeoutError:
                    print(f"Playwright timed out for SharePoint URL: {url}")
                except Exception as e:
                    print(f"Playwright error on SharePoint for {url}: {e}")
                finally:
                    browser.close()
            return {"downloaded_files": saved}
            
        # DTVP / Satellite family
        elif "/Satellite/" in url or "/VMPSatellite/" in url:
            m = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
            if m:
                project_id = m.group(1)
                prefix = "VMPSatellite" if "/VMPSatellite/" in url else "Satellite"
                parts = urlparse(url)
                zip_url = f"{parts.scheme}://{parts.netloc}/{prefix}/public/company/project/{project_id}/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
                
                downloaded_path = download_file(zip_url, output_dir)
                if downloaded_path:
                    saved.append(os.path.abspath(downloaded_path))
                return {"downloaded_files": saved}
        
        # Default handler (for plain URLs or unknown platforms)
        else:
            try:
                # Try to find direct link or ZIP with requests first
                response = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
                response.raise_for_status()

                # Priority 1: ZIP links in href
                soup = BeautifulSoup(response.text, 'html.parser')
                zip_found = False
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if any(keyword in href.lower() for keyword in ['downloadall', 'alleherunterladen', 'alle-dokumente', 'archive']) or \
                       href.lower().endswith(('.zip', '.rar', '.7z')):
                        zip_url = urljoin(url, href)
                        downloaded_path = download_file(zip_url, output_dir)
                        if downloaded_path:
                            saved.append(os.path.abspath(downloaded_path))
                            zip_found = True
                            break # Found a ZIP, prioritize it
                
                if zip_found:
                    return {"downloaded_files": saved}

                # Priority 2: ZIP links in visible text
                for a in soup.find_all('a', href=True):
                    text = a.get_text(strip=True).lower()
                    if any(keyword in text for keyword in ["alle herunterladen", "alle dokumente", "alle als zip", "alles herunterladen", "download all", "download zip", "zip herunterladen", "unterlagen herunterladen", "alle unterlagen", "gesamtpaket", "vergabeunterlagen herunterladen"]):
                        zip_url = urljoin(url, a['href'])
                        downloaded_path = download_file(zip_url, output_dir)
                        if downloaded_path:
                            saved.append(os.path.abspath(downloaded_path))
                            zip_found = True
                            break
                if zip_found:
                    return {"downloaded_files": saved}

                # Priority 3: Individual document links if no ZIP is found
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    parsed_href = urlparse(href)
                    ext = Path(parsed_href.path).suffix.lower()
                    if ext in DOC_EXTS:
                        doc_url = urljoin(url, href)
                        downloaded_path = download_file(doc_url, output_dir)
                        if downloaded_path:
                            saved.append(os.path.abspath(downloaded_path))

            except Exception as e:
                print(f"Requests failed for {url}: {e}")
                # If requests fails, try Playwright as a last resort for general sites
                try:
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        ctx = browser.new_context(
                            accept_downloads=True, locale="de-DE",
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                        )
                        page = ctx.new_page()
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        
                        # Check for "download all" type links in JS-rendered content
                        all_links = page.locator("a[href]").all()
                        zip_found = False
                        for link in all_links:
                            href = link.get_attribute('href')
                            text = link.inner_text().lower()
                            if not href or href.startswith(("javascript:", "#")): continue

                            # Check for direct ZIP downloads
                            if any(keyword in href.lower() for keyword in ['downloadall', 'alleherunterladen', 'alle-dokumente']) or \
                               href.lower().endswith(('.zip', '.rar', '.7z')):
                                doc_url = urljoin(url, href)
                                with page.expect_download() as dl:
                                    link.click()
                                download = dl.value
                                filename = download.suggested_filename
                                filepath = os.path.join(output_dir, filename)
                                download.save_as(filepath)
                                saved.append(os.path.abspath(filepath))
                                zip_found = True
                                break
                            
                            # Check for text indicating "download all"
                            if any(keyword in text for keyword in ["alle herunterladen", "alle dokumente", "alle als zip", "alles herunterladen", "download all", "download zip", "zip herunterladen", "unterlagen herunterladen", "alle unterlagen", "gesamtpaket", "vergabeunterlagen herunterladen"]):
                                doc_url = urljoin(url, href)
                                with page.expect_download() as dl:
                                    link.click()
                                download = dl.value
                                filename = download.suggested_filename
                                filepath = os.path.join(output_dir, filename)
                                download.save_as(filepath)
                                saved.append(os.path.abspath(filepath))
                                zip_found = True
                                break

                        if zip_found:
                             browser.close()
                             return {"downloaded_files": saved}
                        
                        # If no ZIP, download individual files
                        for link in all_links:
                            href = link.get_attribute('href')
                            if not href or href.startswith(("javascript:", "#")): continue
                            
                            parsed_href = urlparse(href)
                            ext = Path(parsed_href.path).suffix.lower()
                            if ext in DOC_EXTS:
                                doc_url = urljoin(url, href)
                                # Check if this link is already downloaded or pending
                                already_downloaded = False
                                for s_path in saved:
                                    if Path(s_path).name in doc_url:
                                        already_downloaded = True
                                        break
                                if already_downloaded: continue

                                try:
                                    with page.expect_download() as dl:
                                        link.click()
                                    download = dl.value
                                    filename = download.suggested_filename
                                    filepath = os.path.join(output_dir, filename)
                                    download.save_as(filepath)
                                    saved.append(os.path.abspath(filepath))
                                except PlaywrightTimeoutError:
                                    print(f"Download timed out for {doc_url}")
                                except Exception as dl_e:
                                    print(f"Error during download of {doc_url}: {dl_e}")
                        browser.close()
                        return {"downloaded_files": saved}
                except Exception as playwright_e:
                    print(f"Playwright failed for general URL {url}: {playwright_e}")
    except Exception as e:
        print(f"General scraping error for {url}: {e}")

    return {"downloaded_files": saved}

# Helper for BeautifulSoup, since it's not a built-in module
try:
    from bs4 import BeautifulSoup
except ImportError:
    print("BeautifulSoup not found. Please install it: pip install beautifulsoup4")
    # Define a dummy BeautifulSoup if not installed, to prevent NameError
    class BeautifulSoup:
        def __init__(self, *args, **kwargs):
            raise ImportError("BeautifulSoup is not installed.")