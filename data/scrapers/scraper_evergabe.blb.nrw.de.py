import os, re, requests, hashlib
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright
import html

DOC_EXTS = {".pdf", ".docx", ".doc", ".zip", ".xml", ".xls", ".xlsx",
            ".ods", ".odt", ".gaeb", ".x81", ".x83", ".ppt", ".pptx", ".txt"}

def scrape(url: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    saved = []
    
    try:
        # DTVP/Satellite platform check
        dtvp_match = re.search(r"/(?:project|notice)/([A-Z0-9]+)(?:/|$)", url, re.IGNORECASE)
        if dtvp_match:
            project_id = dtvp_match.group(1)
            prefix = "VMPSatellite" if "/VMPSatellite/" in url or "/VMP/Satellite/" in url else "Satellite"
            parts = urlparse(url)
            zip_url_dtvp = f"{parts.scheme}://{parts.netloc}/Vergabe/public/company/project/{project_id}/de/documents/archive/Vergabeunterlagen_{project_id}.zip"
            
            try:
                print(f"Attempting direct DTVP ZIP download: {zip_url_dtvp}")
                r = requests.get(zip_url_dtvp, allow_redirects=True, timeout=10)
                r.raise_for_status()
                if 'Content-Type' in r.headers and 'zip' in r.headers['Content-Type']:
                    filename = f"Vergabeunterlagen_{project_id}.zip"
                    filepath = os.path.join(output_dir, filename)
                    with open(filepath, 'wb') as f:
                        f.write(r.content)
                    saved.append(filepath)
                    print(f"Downloaded DTVP ZIP: {filepath}")
                    return {"downloaded_files": saved}
            except requests.exceptions.RequestException as e:
                print(f"Direct DTVP ZIP download failed or was not a ZIP: {e}")
                # Fall through to Playwright if direct download fails or is not a ZIP
        
        # Playwright for other cases or failed DTVP direct download
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                accept_downloads=True, locale="de-DE",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = ctx.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000) # Increased timeout

            # evergabe-online.de (Wicket) specific logic
            # Prioritize "download all" / ZIP
            zip_downloaded = False
            
            # 1. Look for href ending with .zip or containing zipdownloadbutton etc.
            zip_link = page.locator(
                'a[href$=".zip"], '
                'a:has-text("alle herunterladen"i), '
                'a:has-text("alle dokumente"i), '
                'a:has-text("alle als zip"i), '
                'a:has-text("alles herunterladen"i), '
                'a:has-text("download all"i), '
                'a:has-text("download zip"i), '
                'a:has-text("zip herunterladen"i), '
                'a:has-text("unterlagen herunterladen"i), '
                'a:has-text("alle unterlagen"i), '
                'a:has-text("gesamtpaket"i), '
                'a:has-text("vergabeunterlagen herunterladen"i)'
            ).all()

            for link_element in zip_link:
                href = link_element.get_attribute('href')
                text = link_element.text_content()
                if href and (
                    'zipDownloadButton' in href or
                    href.endswith('.zip') or
                    any(phrase in text.lower() for phrase in ["download all", "alle herunterladen", "alle als zip", "zip herunterladen", "alles herunterladen", "unterlagen herunterladen", "alle unterlagen", "gesamtpaket", "vergabeunterlagen herunterladen"])
                ):
                    full_zip_url = urljoin(url, html.unescape(href))
                    try:
                        print(f"Attempting to download ZIP via Playwright click: {full_zip_url}")
                        with page.expect_download(timeout=30000) as download_info:
                            link_element.click(timeout=10000)
                        download = download_info.value
                        download_path = os.path.join(output_dir, download.suggested_filename)
                        download.save_as(download_path)
                        saved.append(download_path)
                        print(f"Downloaded ZIP: {download_path}")
                        zip_downloaded = True
                        break
                    except Exception as dl_e:
                        print(f"Playwright ZIP download failed (click/timeout): {dl_e}")
                        # Try direct requests download if Playwright click fails
                        try:
                            r = requests.get(full_zip_url, allow_redirects=True, timeout=10)
                            r.raise_for_status()
                            if 'Content-Type' in r.headers and 'zip' in r.headers['Content-Type']:
                                filename = download.suggested_filename if download else os.path.basename(urlparse(full_zip_url).path)
                                filepath = os.path.join(output_dir, filename)
                                with open(filepath, 'wb') as f:
                                    f.write(r.content)
                                saved.append(filepath)
                                print(f"Downloaded ZIP via requests: {filepath}")
                                zip_downloaded = True
                                break
                        except requests.exceptions.RequestException as req_e:
                            print(f"Direct requests ZIP download also failed: {req_e}")
                            pass # Continue searching for other options
            
            if zip_downloaded:
                browser.close()
                return {"downloaded_files": saved}
                            
            # If no "download all" ZIP was found or successfully downloaded, look for individual files
            print("No 'download all' ZIP found or downloaded, looking for individual files.")
            for link in page.locator('a[href]').all():
                href = link.get_attribute("href")
                if not href:
                    continue
                
                # Filter out irrelevant links
                if any(ext in href.lower() for ext in ['archivedProcedures.html', 'login.html', '#', 'javascript:']):
                    continue

                full_url = urljoin(url, href)
                parsed_url = urlparse(full_url)
                
                # Check for file extensions
                stem, ext = os.path.splitext(parsed_url.path)
                if ext.lower() in DOC_EXTS:
                    filename = os.path.basename(parsed_url.path) or f"document_{hashlib.md5(full_url.encode()).hexdigest()}{ext}"
                    filepath = os.path.join(output_dir, filename)

                    print(f"Found individual document link: {full_url}")
                    try:
                        # Try to download directly using requests
                        r = requests.get(full_url, allow_redirects=True, timeout=10)
                        r.raise_for_status() # Raise an exception for bad status codes
                        
                        # Use Content-Disposition filename if available
                        if 'content-disposition' in r.headers:
                            cd = r.headers['content-disposition']
                            fname_match = re.findall(r'filename\*?=(?:UTF-8\'\')?\"?([^;"]+)\"?>', cd)
                            if fname_match:
                                filename = requests.utils.unquote(fname_match[0], encoding='utf-8')
                        
                        # Ensure filename has a valid extension, try to get from content-type if not
                        if not os.path.splitext(filename)[1] and 'content-type' in r.headers:
                            content_type = r.headers['content-type'].split(';')[0]
                            # Example: map 'application/pdf' to '.pdf'
                            if 'pdf' in content_type: ext_from_type = '.pdf'
                            elif 'word' in content_type: ext_from_type = '.doc'
                            elif 'excel' in content_type: ext_from_type = '.xls'
                            elif 'zip' in content_type: ext_from_type = '.zip'
                            else: ext_from_type = '' # Unknown type
                            filename = filename + ext_from_type if ext_from_type else filename

                        filepath = os.path.join(output_dir, filename)

                        with open(filepath, 'wb') as f:
                            f.write(r.content)
                        saved.append(filepath)
                        print(f"Downloaded individual file: {filepath}")

                    except requests.exceptions.RequestException as req_e:
                        print(f"Failed to download {full_url} directly: {req_e}")
                    except Exception as download_err:
                        print(f"An unexpected error occurred during direct download of {full_url}: {download_err}")

            browser.close()

    except Exception as e:
        print(f"An error occurred during scraping: {e}")
        # Log the exception for debugging
        import traceback
        traceback.print_exc()

    return {"downloaded_files": saved}