import asyncio
import json
import os
import re
from playwright.sync_api import sync_playwright, Playwright, Browser, Page, BrowserContext, Error
from typing import Dict, List, Any, Optional

def scrape(url: str, output_dir: str) -> Dict[str, List[Any]]:
    """
    Scrapes tender information and downloads attached documents from a given URL.

    Args:
        url: The URL of the tender portal.
        output_dir: The directory to save downloaded files.

    Returns:
        A dictionary containing a list of scraped tenders and a list of downloaded file paths.
    """
    downloaded_files = []
    tenders_data = []

    # Ensure output directory exists
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    def handle_download(download, target_dir):
        try:
            # Generate a unique filename to avoid collisions and handle missing filenames
            original_filename = download.suggested_filename
            if not original_filename:
                original_filename = f"download_{hash(download.url)}.tmp"

            # Clean filename to remove invalid characters and ensure it's safe
            safe_filename = re.sub(r'[<>:"/\\|?*]', '_', original_filename)
            if not safe_filename: # If all characters were invalid
                safe_filename = f"download_{hash(download.url)}.tmp"

            filepath = os.path.join(target_dir, safe_filename)

            # Handle potential filename collisions
            counter = 1
            base, ext = os.path.splitext(filepath)
            while os.path.exists(filepath):
                filepath = f"{base}_{counter}{ext}"
                counter += 1

            download.save_as(filepath)
            print(f"Downloaded: {filepath}")
            downloaded_files.append(os.path.abspath(filepath))
        except Exception as e:
            print(f"Error saving download: {e}")

    def get_page_content(page: Page, selector: str) -> str | None:
        element = page.query_selector(selector)
        if element:
            return element.text_content()
        return None

    def get_element_attribute(page: Page, selector: str, attribute: str) -> str | None:
        element = page.query_selector(selector)
        if element:
            return element.get_attribute(attribute)
        return None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Intercept downloads
        page.on("download", lambda download: handle_download(download, output_dir))

        # Intercept network responses for potential file downloads
        def handle_response(response):
            content_type = response.headers.get("content-type", "")
            url = response.url
            if any(mime_type in content_type for mime_type in ["application/pdf", "application/octet-stream", "application/zip", "application/msword", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.ms-excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.rar", "image/jpeg", "image/png", "application/xml", "text/csv", "application/vnd.ms-powerpoint", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/x-rar-compressed"]):
                try:
                    # Attempt to get filename from Content-Disposition header first
                    content_disposition = response.headers.get("content-disposition", "")
                    filename = None
                    if "filename=" in content_disposition:
                        filename = re.findall('filename="?(.+)"?', content_disposition)[0]
                    elif "filename*=" in content_disposition:
                        filename = re.findall("filename\*=UTF-8''(.+)", content_disposition)[0]
                        filename = PercentEncoder.decode(filename) # URL decoding
                    else:
                        # Fallback to extracting from URL
                        filename = url.split('/')[-1]
                        # Remove query parameters if any
                        filename = filename.split('?')[0]

                    if not filename:
                        filename = f"network_download_{hash(url)}.tmp"

                    safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                    if not safe_filename:
                        safe_filename = f"network_download_{hash(url)}.tmp"

                    filepath = os.path.join(output_dir, safe_filename)

                    counter = 1
                    base, ext = os.path.splitext(filepath)
                    while os.path.exists(filepath):
                        filepath = f"{base}_{counter}{ext}"
                        counter += 1

                    with open(filepath, "wb") as f:
                        f.write(response.body())
                    print(f"Downloaded via network intercept: {filepath}")
                    downloaded_files.append(os.path.abspath(filepath))
                except Exception as e:
                    print(f"Error saving network download: {e} for URL: {url}")

        page.on("response", handle_response)

        try:
            print(f"Navigating to: {url}")
            page.goto(url, wait_until="networkidle")

            # --- Extract Tender Details ---
            tender_info = {}

            # Tender title/subject
            tender_info["title"] = get_page_content(page, "h2")
            if not tender_info["title"]:
                 tender_info["title"] = get_page_content(page, ".tender-title") # Example fallback

            # Contracting authority
            tender_info["authority"] = get_page_content(page, ".contracting-authority")
            if not tender_info["authority"]:
                # Try to find it more generally if specific class is not available
                authority_label_element = page.query_selector('td:has-text("Auftraggeber") + td')
                if authority_label_element:
                    tender_info["authority"] = authority_label_element.text_content()
                else:
                    tender_info["authority"] = None # Explicitly set to None

            # Publication date
            publication_date_element = page.query_selector('td:has-text("Ver&ouml;ffentlichungsdatum") + td')
            if publication_date_element:
                tender_info["publication_date"] = publication_date_element.text_content()
            else:
                publication_date_element = page.query_selector('td:has-text("Datum der Veröffentlichung") + td')
                if publication_date_element:
                    tender_info["publication_date"] = publication_date_element.text_content()
                else:
                    tender_info["publication_date"] = None


            # Submission deadline
            deadline_element = page.query_selector('td:has-text("Enddatum der Angebote") + td')
            if deadline_element:
                tender_info["deadline"] = deadline_element.text_content()
            else:
                deadline_element = page.query_selector('td:has-text("Angebotsfrist") + td')
                if deadline_element:
                    tender_info["deadline"] = deadline_element.text_content()
                else:
                    tender_info["deadline"] = None


            # Tender reference/ID
            ref_element = page.query_selector('td:has-text("Vergabenummer") + td')
            if ref_element:
                 tender_info["reference_id"] = ref_element.text_content()
            else:
                ref_element = page.query_selector('td:has-text("Aktenzeichen") + td')
                if ref_element:
                    tender_info["reference_id"] = ref_element.text_content()
                else:
                    # Fallback: try to extract from URL if it's a unique identifier
                    match = re.search(r"TWOID=([\w-]+)", url)
                    if match:
                        tender_info["reference_id"] = match.group(1)
                    else:
                        tender_info["reference_id"] = None


            # Short description/summary
            tender_info["description"] = get_page_content(page, ".tender-description")
            if not tender_info["description"]:
                # Try to find a general description area
                description_label = page.query_selector('td:has-text("Kurzbeschreibung") + td')
                if description_label:
                    tender_info["description"] = description_label.text_content()
                else:
                    tender_info["description"] = None

            # Category/CPV codes
            cpv_element = page.query_selector('td:has-text("CPV-Code") + td')
            if cpv_element:
                tender_info["cpv_codes"] = cpv_element.text_content()
            else:
                tender_info["cpv_codes"] = None

            # Direct URL
            tender_info["url"] = url

            # Other metadata - this is a place holder, needs inspection of the HTML
            # For example, if there's a table with more details:
            details_table = page.query_selector(".tender-details-table") # Example selector
            if details_table:
                rows = details_table.query_selector_all("tr")
                for row in rows:
                    cells = row.query_selector_all("td")
                    if len(cells) == 2:
                        key = cells[0].text_content().strip()
                        value = cells[1].text_content().strip()
                        # Avoid overwriting essential fields if they match
                        if key and value and key.lower() not in ["auftraggeber", "ver pubblici", "angebot", "aktenzeichen"]:
                             # Simple camelCase conversion for keys if needed
                            clean_key = re.sub(r'\s+', '_', key).lower()
                            tender_info[clean_key] = value


            tenders_data.append(tender_info)

            # --- Download Documents ---
            # Look for links that are likely document downloads
            # Common patterns: href ending in .pdf, .doc, .docx, .xls, .xlsx, .zip, etc.
            # Also look for text like "Dokumente", "Unterlagen", "Download" within anchor tags.
            download_links = page.query_selector_all("a[href]")
            for link in download_links:
                href = link.get_attribute("href")
                if href:
                    # Construct the absolute URL if it's relative
                    if not href.startswith("http"):
                        base_url_match = re.match(r"(.*://[^/]+)", url)
                        if base_url_match:
                            base_url = base_url_match.group(1)
                            href = os.path.join(base_url, href).replace("\\", "/")
                        else:
                            print(f"Could not determine base URL for relative href: {href}")
                            continue

                    link_text = link.text_content().strip().lower()
                    file_extension_match = re.search(r'\.(pdf|doc|docx|xls|xlsx|zip|xml|csv|ppt|pptx|jpg|png|rar)(\?.*)?$', href, re.IGNORECASE)

                    if file_extension_match or "download" in link_text or "unterlagen" in link_text or "dokument" in link_text:
                        print(f"Attempting to download from link: {href} (text: {link.text_content().strip()})")
                        try:
                            # Use page.goto to trigger download if it's a direct link
                            # For JS-triggered downloads, expect_download is better
                            if page.url != href: # Avoid navigating to the current page
                                # Check if it's a relative path that might need context
                                if not href.startswith("http"):
                                     target_href = page.url + (href if href.startswith('/') else '/' + href)
                                else:
                                     target_href = href

                                # Some links might be within iframes. Need to check frames.
                                found_in_frame = False
                                for frame in page.frames:
                                    try:
                                        # Try to click within the frame
                                        frame_link = frame.query_selector(f'a[href="{link.get_attribute("href")}"]')
                                        if frame_link:
                                            with page.expect_download() as download_info:
                                                frame_link.click()
                                            download = download_info.value
                                            handle_download(download, output_dir)
                                            found_in_frame = True
                                            break
                                    except Exception:
                                        pass # ignore errors, try next frame
                                if found_in_frame:
                                    continue

                                # If not found in frame, try direct click on main page
                                with page.expect_download() as download_info:
                                    link.click()
                                download = download_info.value
                                handle_download(download, output_dir)

                        except Error as e:
                            print(f"Playwright error during download attempt for {href}: {e}")
                        except Exception as e:
                            print(f"General error during download attempt for {href}: {e}")


        except Error as e:
            print(f"Playwright error navigating to {url}: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    # Save scraped data to JSON
    try:
        with open(os.path.join(output_dir, "tenders.json"), "w", encoding="utf-8") as f:
            json.dump({"tenders": tenders_data, "downloaded_files": downloaded_files}, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving tenders.json: {e}")

    return {
        "tenders": tenders_data,
        "downloaded_files": downloaded_files
    }

class PercentEncoder:
    @staticmethod
    def decode(string):
        return re.sub(r"%([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), string)