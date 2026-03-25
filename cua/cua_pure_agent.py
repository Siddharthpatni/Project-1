#!/usr/bin/env python3
"""
cua_pure_agent.py — Pure Computer-Use Agent (CUA) for Tender Document Downloading

This script strictly follows the "Final Week Goals" architecture:
LLM-Agent -> Actions (click x,y) -> Tender Websites -> New GUI State -> LLM-Agent.

It relies entirely on an LLM interacting with the browser GUI via `browser-use`, 
with ZERO hardcoded XPath or heuristic fallback layers.

Requirements:
    pip install browser-use langchain-openai python-dotenv
    playwright install chromium
"""

import asyncio
import argparse
import csv
import logging
import os
import sys
from dotenv import load_dotenv

# Import the CUA framework components
from browser_use.llm.openrouter.chat import ChatOpenRouter
from browser_use import Agent, Browser

load_dotenv()

# ── Logging Setup ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CUA] %(message)s",
    handlers=[
        logging.FileHandler("cua_agent.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("cua")

load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════
#  CUA AGENT TASK DEFINITION
# ═══════════════════════════════════════════════════════════════════════════

def build_agent_task(url: str) -> str:
    """
    This is the core prompt driving the GUI agent's behavior.
    It instructs the agent on how to interact with the page visually/structurally.
    """
    return f"""
    Your objective is to download public procurement tender documents from a German website.
    
    Target URL: {url}
    
    Instructions:
    1. Navigate to the Target URL.
    2. Immediately look for a cookie consent banner. If present, click "Akzeptieren", "Alle akzeptieren", or "Zustimmen".
    3. Look for a section, tab, or button related to documents. Common German labels include "Vergabeunterlagen", "Dokumente", or "Unterlagen". Click it to reveal the files.
    4. Identify links or buttons to download PDF or ZIP files. 
    6. Click the download buttons/links to initiate the downloads.
    7. VISUAL VERIFICATION: Before finishing, look at the screen and confirm that the documents you intended to download are indeed represented as having been clicked or initiated. If there is a "Downloads" status or a change in the button state, verify it visually.
    8. Once you have successfully initiated the downloads and visually verified the action, conclude the task successfully.
    """

# ═══════════════════════════════════════════════════════════════════════════
#  AGENT EXECUTION
# ═══════════════════════════════════════════════════════════════════════════

async def run_cua_for_url(url: str, llm: ChatOpenRouter, headless: bool = False):
    """
    Spins up a fresh browser session for the agent to complete its task.
    """
    log.info(f"Initiating CUA sequence for: {url}")
    
    # Configure persistent download directory
    downloads_path = os.path.join(os.getcwd(), "downloads")
    os.makedirs(downloads_path, exist_ok=True)
    log.info(f"💾 Downloads will be saved to: {downloads_path}")

    # Configure browser. Setting headless=False is highly recommended for
    # debugging CUAs so you can watch the agent click and type.
    browser = Browser(headless=headless, downloads_path=downloads_path)
    task_prompt = build_agent_task(url)
    
    agent = Agent(
        task=task_prompt,
        llm=llm,
        browser=browser
    )
    
    try:
        # The agent enters its Observation -> Action -> State loop here
        result = await agent.run()
        log.info(f"Agent finished task for {url}.")
        log.debug(f"Agent History/Result: {result}")
        return True
    except Exception as e:
        log.error(f"Agent failed or crashed on {url}: {e}")
        return False
    finally:
        await browser.stop()

# ═══════════════════════════════════════════════════════════════════════════
#  MAIN LOOP
# ═══════════════════════════════════════════════════════════════════════════

async def main(args):
    api_key = args.api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        log.error("OPENROUTER_API_KEY is missing. Please set it in your .env file or pass via --api-key.")
        sys.exit(1)

    # Note: CUAs are vision and DOM heavy. While qwen3-14b or gemini-flash-lite 
    # might work, stronger models like gpt-4o or claude-3.5-sonnet usually perform 
    # much better for GUI tasks.
    llm = ChatOpenRouter(
        model=args.model,
        api_key=api_key,
    )

    # Read target URLs
    urls = []
    if not os.path.exists(args.input):
        log.error(f"Input file not found: {args.input}")
        sys.exit(1)
        
    with open(args.input, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("url", "").strip():
                urls.append(row["url"].strip())

    if args.limit > 0:
        urls = urls[:args.limit]

    log.info(f"Loaded {len(urls)} URLs. Starting CUA experiments...")

    # Run the agent sequentially (parallelizing GUI agents requires heavy system resources)
    success_count = 0
    for i, url in enumerate(urls, 1):
        log.info(f"--- Processing {i}/{len(urls)} ---")
        success = await run_cua_for_url(url, llm, headless=args.headless)
        if success:
            success_count += 1
            
    log.info("==================================================")
    log.info(f"Experiment Complete. Agent succeeded on {success_count}/{len(urls)} URLs.")
    log.info("==================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pure CUA GUI Agent for Tender Downloading")
    parser.add_argument("-i", "--input", default="publications_b.csv", help="Input CSV file")
    parser.add_argument("-n", "--limit", type=int, default=0, help="Max URLs to process (0 = all)")
    parser.add_argument("--api-key", default=None, help="OpenRouter API Key")
    parser.add_argument("--model", default="google/gemini-2.5-flash", help="LLM to drive the agent")
    parser.add_argument("--headless", action="store_true", help="Run browser in background (hidden)")
    
    args = parser.parse_args()
    asyncio.run(main(args))