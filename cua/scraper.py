import os
import asyncio
import csv
import logging
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv

# ====== CONFIG ======
MAX_CONCURRENT = 10
DOWNLOAD_DIR = "downloads"
LOG_FILE = "scraper.log"

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

# ====== UTIL ======
def safe_filename(url):
    return url.replace("https://", "").replace("/", "_")[:100]

# ====== LAYER 1: FAST SCRAPER ======
async def fast_scrape(page):
    try:
        if await page.locator("text=Vergabeunterlagen").count() > 0:
            await page.locator("text=Vergabeunterlagen").first.click()
            return True

        if await page.locator("text=Dokumente").count() > 0:
            await page.locator("text=Dokumente").first.click()
            return True

        return False
    except:
        return False

# ====== LAYER 2: HEURISTIC ======
async def heuristic_scrape(page):
    keywords = ["Download", "Unterlagen", "PDF", "ZIP"]

    for word in keywords:
        loc = page.locator(f"text={word}")
        if await loc.count() > 0:
            try:
                await loc.first.click()
                return True
            except:
                continue
    return False

# ====== LAYER 3: CUA AGENT ======
async def run_agent(url):
    from browser_use.llm.openrouter.chat import ChatOpenRouter
    from browser_use import Agent, Browser
    from dotenv import load_dotenv
    load_dotenv()

    llm = ChatOpenRouter(
        model="google/gemini-2.5-flash-lite",
    )

    downloads_path = os.path.join(os.getcwd(), "downloads")
    os.makedirs(downloads_path, exist_ok=True)
    browser = Browser(headless=True, downloads_path=downloads_path)

    task = f"""
    Objective: Download all tender documents from {url}.
    
    1. Navigate to the page.
    2. Handle cookie banners.
    3. Locate 'Vergabeunterlagen' or 'Downloads'.
    4. Download all available files (PDF/ZIP).
    5. VISUAL VERIFICATION: Before concluding, use your vision to confirm that all visible download links were clicked and that the documents were successfully initiated. 
    6. Finish once verified.
    """

    agent = Agent(task=task, llm=llm, browser=browser)

    try:
        await agent.run()
        return True
    except Exception as e:
        logging.error(f"Agent failed: {e}")
        return False

# ====== DOWNLOAD HANDLER ======
async def handle_download(page, url):
    try:
        async with page.expect_download(timeout=10000) as download_info:
            await page.click("a[href$='.pdf'], a[href$='.zip']")
        download = await download_info.value

        filename = safe_filename(url) + "_" + download.suggested_filename
        path = os.path.join(DOWNLOAD_DIR, filename)
        await download.save_as(path)

        logging.info(f"Downloaded: {filename}")
        return True
    except:
        return False

# ====== MAIN WORKER ======
async def process_url(browser, url):
    context = await browser.new_context(accept_downloads=True)
    page = await context.new_page()

    try:
        await page.goto(url, timeout=30000)

        # Accept cookies if exists
        try:
            await page.click("text=Accept", timeout=3000)
        except:
            pass

        # LAYER 1
        if await fast_scrape(page):
            if await handle_download(page, url):
                return "fast_success"

        # LAYER 2
        if await heuristic_scrape(page):
            if await handle_download(page, url):
                return "heuristic_success"

        # LAYER 3
        if await run_agent(url):
            return "agent_success"

        return "failed"

    except Exception as e:
        logging.error(f"{url} failed: {e}")
        return "error"

    finally:
        await context.close()

# ====== RUNNER ======
async def run_scraper(input_csv):
    Path(DOWNLOAD_DIR).mkdir(exist_ok=True)

    urls = []
    with open(input_csv, "r") as f:
        reader = csv.reader(f)
        urls = [row[0] for row in reader]

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        sem = asyncio.Semaphore(MAX_CONCURRENT)

        async def sem_task(url):
            async with sem:
                return await process_url(browser, url)

        results = await asyncio.gather(*[sem_task(url) for url in urls])

        await browser.stop()

    # Summary
    logging.info("==== SUMMARY ====")
    logging.info(f"Total: {len(results)}")
    logging.info(f"Success: {results.count('fast_success') + results.count('heuristic_success') + results.count('agent_success')}")
    logging.info(f"Failed: {results.count('failed')}")

# ====== ENTRY ======
if __name__ == "__main__":
    asyncio.run(run_scraper("publications_b.csv"))