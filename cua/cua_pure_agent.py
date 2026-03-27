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
import time
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

# ── TIMEOUT CONFIGURATION ──────────────────────────────────────────────────
# Increased from 40s to 60s to handle slow "Bieter" portals and heavy DOMs
os.environ["TIMEOUT_NavigateToUrlEvent"] = "60.0"
os.environ["TIMEOUT_BrowserStateRequestEvent"] = "60.0"
os.environ["TIMEOUT_ClickElementEvent"] = "60.0"
os.environ["TIMEOUT_WaitEvent"] = "60.0"
os.environ["TIMEOUT_FileDownloadedEvent"] = "60.0"
# ───────────────────────────────────────────────────────────────────────────

from browser_use.llm.openrouter.chat import ChatOpenRouter
from browser_use import Agent, Browser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CUA] %(message)s",
    handlers=[
        logging.FileHandler("cua_agent.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("cua")

stats = {
    "total_calls": 0,
    "retries": 0,
    "total_tokens": 0,
    "total_cost": 0.0,
    "model_usage": {},
    "calls_per_domain": {},
    "url_recoveries": {}
}

# ═══════════════════════════════════════════════════════════════════════════
#  CUA AGENT TASK DEFINITION
# ═══════════════════════════════════════════════════════════════════════════

def build_agent_task(url: str) -> str:
    """
    Core prompt driving the GUI agent's behavior.
    """
    return f"""
    Your objective is to download public procurement tender documents from a German website.
    
    Target URL: {url}
    
    Instructions:
    1. Navigate to the Target URL.
    2. Handle Cookies: Look for a cookie consent banner. If present, click "Akzeptieren", "Alle akzeptieren", or "Zustimmen".
    3. EARLY EXIT (EXPIRED/MISSING): Immediately scan the page text. If the tender is clearly expired (look for terms like "abgelaufen", "nicht mehr aktiv", "aufgehoben", "beendet", "Frist abgelaufen") or documents are explicitly missing, STOP immediately and conclude. Do not waste steps searching for files that do not exist.
    4. Open Tender Details: If you land on a page with a table/list of tenders and NO immediate document buttons, click on the tender's title (usually a blue hyperlink) or an info icon (e.g., "i") to open the details modal.
    5. Locate the Files: Scan the page to find where the documents are located. If they are hiding behind a hyperlink, tab, or button that opens a popup/modal, use your intuition to find and open that section.
    6. HIGHEST PRIORITY - "Download All" / "Extract" / "Extract all" / "Extract Tender" / ZIP: ALWAYS check first if there is a single button to download everything at once (e.g., "Alle Unterlagen herunterladen", "Als ZIP", "Gesamtdownload", or a "Select All" checkbox + download). If you successfully trigger this, you are DONE. Do not click individual files.
    7. Handle Individual Files: If NO bulk download option exists, locate and click ALL unique individual download buttons for the listed files in ONE step if possible.
    8. MEMORY & TRUST YOUR CLICKS (CRITICAL): You MUST memorize every button you click. Browser downloads happen silently in the background. The UI WILL NOT change after you click download. 
       - If you have clicked a download button ONCE, it registered 100%. 
       - DO NOT verify. DO NOT wait for a confirmation. 
       - NEVER click the exact same button twice under ANY circumstances. Move immediately to the next file or conclude.
    9. Handle Redirects & In-Browser PDFs (BOOMERANG RULE): Sometimes a download link redirects you to a COMPLETELY DIFFERENT website or opens a PDF directly. Wh
       - IF this happens, locate and click the final download/save button on that new page.
       - AFTER the download starts, you MUST use the browser's "Go Back" action to return to the original document list so you can continue OR if there is no "Go Back" action, close the tab to return to the tender page.
    10. Check for More: After your first batch of clicks, scroll down ONCE. If you see more documents that you haven't downloaded yet, click them. If NO new buttons appear, CONCLUDE immediately. 
    11. Hard Limit: Do NOT exceed 25 steps. If you are stuck in a loop repeating the exact same actions, STOP and finish.
    """

# ═══════════════════════════════════════════════════════════════════════════
#  AGENT EXECUTION
# ═══════════════════════════════════════════════════════════════════════════

async def run_cua_for_url(url: str, llm: ChatOpenRouter, headless: bool = False):
    log.info(f"Initiating CUA sequence for: {url}")
    
    domain = urlparse(url).netloc
    downloads_path = os.path.join(os.getcwd(), "downloads", domain)
    os.makedirs(downloads_path, exist_ok=True)
    log.info(f"💾 Downloads for {domain} will be saved to: {downloads_path}")

    before_files = set(os.listdir(downloads_path)) if os.path.exists(downloads_path) else set()

    browser = Browser(headless=headless, downloads_path=downloads_path)
    task_prompt = build_agent_task(url)
    
    agent = Agent(
        task=task_prompt,
        llm=llm,
        browser=browser,
        max_steps=25,             
        max_actions_per_step=30   
    )

    start_time = time.time()
    result_data = {
        "url": url,
        "domain": domain,
        "status": "failed",
        "ms": 0,
        "downloaded_docs": [],
        "url_recovery": None
    }

    try:
        result = await agent.run()
        
        # --- WAIT LOGIC FOR MULTIPLE / HEAVY DOWNLOADS ---
        wait_time = 0
        max_wait = 300  # Increased to 5 minutes to allow heavy multi-file operations to finish
        while wait_time < max_wait:
            current_files = os.listdir(downloads_path) if os.path.exists(downloads_path) else []
            # Chromium uses .crdownload, Firefox uses .part for active downloads
            if any(f.endswith('.crdownload') or f.endswith('.part') for f in current_files):
                log.info(f"⏳ Files are still downloading in {domain}... waiting ({wait_time}s / {max_wait}s)")
                await asyncio.sleep(5)
                wait_time += 5
            else:
                break
        # ------------------------------------------------------

        is_actually_successful = any(h.result[-1].is_done for h in result.history if h.result) if result.history else False
        
        after_files = set(os.listdir(downloads_path)) if os.path.exists(downloads_path) else set()
        new_files = list(after_files - before_files)
        
        if is_actually_successful or len(new_files) > 0:
            result_data["status"] = "success"
        else:
            result_data["status"] = "failed"
            
        result_data["downloaded_docs"] = new_files
        result_data["url_recovery"] = "cua_agent"
        
        if result.usage:
            stats["total_tokens"] += result.usage.total_tokens
            cost = result.usage.total_cost
            if cost == 0 and result.usage.total_tokens > 0:
                cost = (result.usage.total_tokens / 1_000_000) * 0.15
            
            stats["total_cost"] += cost
            stats["total_calls"] += 1
            model_name = getattr(llm, "model_name", "unknown")
            stats["model_usage"][model_name] = stats["model_usage"].get(model_name, 0) + 1
            stats["calls_per_domain"][domain] = stats["calls_per_domain"].get(domain, 0) + 1

    except Exception as e:
        log.error(f"Agent failed or crashed on {url}: {e}")
        result_data["status"] = "error"
    finally:
        result_data["ms"] = (time.time() - start_time) * 1000
        await browser.stop()
        return result_data

# ---------------------------------------------------------------------------
# PRINT SUMMARY
# ---------------------------------------------------------------------------
def print_summary(results, use_llm, download_docs):
    t   = len(results) or 1
    ok  = sum(1 for x in results if x["status"] == "success")
    err = sum(1 for x in results if x["status"] == "error")
    to  = sum(1 for x in results if x["status"] == "timeout")
    inv = sum(1 for x in results if x["status"] == "invalid")
    exp = sum(1 for x in results if x["status"] == "expired")
    avg = sum(x["ms"] for x in results) / t
    
    all_docs = []
    for x in results:
        all_docs.extend(x.get("downloaded_docs", []))
    total_docs = len(list(set(all_docs)))
    
    recovered  = sum(1 for x in results if x.get("url_recovery"))

    mode_label = "Phase 2 - LLM" if use_llm else "Phase 1 - XPath"
    print(f"\n{'='*62}")
    print(f"  RESULTS ({mode_label})")
    print(f"{'='*62}")
    print(f"  total:          {t}")
    print(f"  success:        {ok}  ({100*ok/t:.1f}%)")
    print(f"  errors:         {err}  ({100*err/t:.1f}%)")
    print(f"  expired (dead): {exp}  ({100*exp/t:.1f}%)")
    print(f"  timeouts:       {to}  ({100*to/t:.1f}%)")
    print(f"  invalid:        {inv}  ({100*inv/t:.1f}%)")
    print(f"  URL recovered:  {recovered}  ({100*recovered/t:.1f}%)")
    print(f"  avg time:       {avg:.0f}ms/url")
    if download_docs:
        print(f"  docs saved:     {total_docs}")

    if stats["url_recoveries"]:
        print(f"\n  URL RECOVERY BREAKDOWN:")
        for strategy, count in sorted(stats["url_recoveries"].items(), key=lambda x: -x[1]):
            print(f"    {strategy:25s}: {count}")

    print(f"{'='*62}")

    if use_llm and stats["total_calls"]:
        print(f"\n  LLM STATS:")
        print(f"    api calls:     {stats['total_calls']}")
        print(f"    retries:       {stats['retries']}")
        print(f"    total tokens:  {stats['total_tokens']:,}")
        print(f"    total cost:    ${stats['total_cost']:.4f}")
        print(f"    avg tok/call:  {stats['total_tokens']//stats['total_calls']}")
        print(f"    models used:")
        for m, c in stats["model_usage"].items():
            print(f"      {m}: {c} calls")
        print(f"{'='*62}")

    dom_stats = {}
    for x in results:
        d = x["domain"]
        dom_stats.setdefault(d, [0, 0])
        dom_stats[d][1] += 1
        if x["status"] == "success":
            dom_stats[d][0] += 1

    print("\n  domains:")
    for d, (s, tot) in sorted(dom_stats.items(), key=lambda x: -x[1][1]):
        calls = stats["calls_per_domain"].get(d, 0)
        call_str = f"  calls: {calls}" if use_llm else ""
        print(f"    {d:48s} {s:>4}/{tot:<4} ({100*s/tot:.0f}%){call_str}")
    print()

async def main(args):
    api_key = args.api_key or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        log.error("OPENROUTER_API_KEY is missing. Please set it in your .env file or pass via --api-key.")
        sys.exit(1)

    llm = ChatOpenRouter(
        model=args.model,
        api_key=api_key,
    )

    urls = []
    if args.url:
        urls = [args.url.strip()]
        log.info(f"Using single URL provided via --url.")
    else:
        if not os.path.exists(args.input):
            log.error(f"Input file not found: {args.input}")
            sys.exit(1)
            
        with open(args.input, encoding="utf-8") as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) > 4:
                    url = row[4].strip()
                    if url.startswith("http"):
                        urls.append(url)

        if args.limit > 0:
            urls = urls[:args.limit]
        
        log.info(f"Loaded {len(urls)} URLs from {args.input}.")

    log.info("Starting CUA experiments...")

    all_results = []
    for i, url in enumerate(urls, 1):
        log.info(f"--- Processing {i}/{len(urls)} ---")
        res = await run_cua_for_url(url, llm, headless=args.headless)
        all_results.append(res)
            
    print_summary(all_results, use_llm=True, download_docs=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pure CUA GUI Agent for Tender Downloading")
    parser.add_argument("-i", "--input", default="publications_b.csv", help="Input CSV file")
    parser.add_argument("-n", "--limit", type=int, default=0, help="Max URLs to process (0 = all)")
    parser.add_argument("--url", help="Run a specific URL directly (bypasses CSV)")
    parser.add_argument("--api-key", default=None, help="OpenRouter API Key")
    parser.add_argument("--model", default="google/gemini-2.5-pro", help="LLM to drive the agent")
    parser.add_argument("--headless", action="store_true", help="Run browser in background (hidden)")
    
    args = parser.parse_args()
    asyncio.run(main(args))