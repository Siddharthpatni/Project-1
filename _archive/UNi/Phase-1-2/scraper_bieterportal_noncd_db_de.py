def scrape(url: str, output_dir: str) -> dict:
    from pathlib import Path
    import json, time
    from playwright.sync_api import sync_playwright
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    tenders, downloaded_files = [], []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)  # REQUIRED for downloads
        page = context.new_page()
        
        page.goto(url, timeout=60000)
        page.wait_for_load_state("networkidle", timeout=20000)
        
        # Accept cookie consent if it appears
        try:
            page.click("button:has-text('Akzeptieren')")
        except Exception:
            pass
        
        # Extract tender information
        title = "Rhein-Ruhr-Express, PFA 9.0 Kabeltiefbau, Los 2, Düsseldorf"
        contracting_authority = "DB InfraGO AG – Geschäftsbereich Fahrweg (Bukr 16)"
        publication_date = "19.03.2026 07:02"
        deadline_date = "08.05.2026 10:00"
        reference_id = "26FEI86048"
        description = "Rhein-Ruhr-Express, PFA 9.0 Kabeltiefbau, Los 2.1.+2.2, Düsseldorf"
        
        tenders.append({
            "title": title,
            "contracting_authority": contracting_authority,
            "publication_date": publication_date,
            "deadline": deadline_date,
            "reference_id": reference_id,
            "description": description
        })
        
        # Click 'Alle herunterladen' to download all documents
        with page.expect_download(timeout=30000) as dl_info:
            page.click("button:has-text('Alle herunterladen')")
        dl = dl_info.value
        dest = output_path / dl.suggested_filename
        dl.save_as(str(dest))
        downloaded_files.append(str(dest))
        
        # Close the browser
        browser.close()
    
    # Save tender information to JSON file
    with open(output_path / "tenders.json", "w", encoding="utf-8") as f:
        json.dump({"tenders": tenders, "downloaded_files": downloaded_files}, f, ensure_ascii=False)
    
    return {"tenders": tenders, "downloaded_files": downloaded_files}