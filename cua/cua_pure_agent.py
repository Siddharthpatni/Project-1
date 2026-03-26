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
from urllib.parse import urlparse
import time

# Global stats tracker
stats = {
    "total_calls": 0,
    "retries": 0,
    "total_tokens": 0,
    "total_cost": 0.0,
    "model_usage": {},
    "calls_per_domain": {},
    "url_recoveries": {}
}


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
    3. Look for a section or button related to documents (e.g., "Vergabeunterlagen", "Dokumente"). Click it.
    4. Once the document list is visible, click ALL unique "Datei herunterladen" (Download file) buttons in ONE step if possible.
    5. CRITICAL: You must STOP once you have clicked the visible buttons. Do NOT click the same button more than once.
    6. If you see a "Download" has started or the file is in `available_file_paths`, DO NOT click it again.
    7. After your first batch of clicks, scroll down ONCE to check for more. If no new buttons appear, CONCLUDE immediately. 
    8. Do NOT exceed 10 steps for a single page. If you are repeating actions, STOP and finish.
    """

# ═══════════════════════════════════════════════════════════════════════════
#  AGENT EXECUTION
# ═══════════════════════════════════════════════════════════════════════════

async def run_cua_for_url(url: str, llm: ChatOpenRouter, headless: bool = False):
    """
    Spins up a fresh browser session for the agent to complete its task.
    """
    log.info(f"Initiating CUA sequence for: {url}")
    
    # Configure persistent download directory organized by domain
    domain = urlparse(url).netloc
    downloads_path = os.path.join(os.getcwd(), "downloads", domain)
    os.makedirs(downloads_path, exist_ok=True)
    log.info(f"💾 Downloads for {domain} will be saved to: {downloads_path}")

    # Snapshot files before run to detect new ones
    before_files = set(os.listdir(downloads_path)) if os.path.exists(downloads_path) else set()

    # Configure browser. Setting headless=False is highly recommended for
    # debugging CUAs so you can watch the agent click and type.
    browser = Browser(headless=headless, downloads_path=downloads_path)
    task_prompt = build_agent_task(url)
    
    agent = Agent(
        task=task_prompt,
        llm=llm,
        browser=browser,
        max_steps=15,  # Prevent runaway loops (like Step 55 in your log)
        max_actions_per_step=10  # Allow multiple clicks in one vision frame
    )
    
    start_time = time.time()
    domain = urlparse(url).netloc
    result_data = {
        "url": url,
        "domain": domain,
        "status": "failed",
        "ms": 0,
        "downloaded_docs": [],
        "url_recovery": None
    }

    try:
        # The agent enters its Observation -> Action -> State loop here
        result = await agent.run()
        
        # Detect new files by snapshotting the folder again
        after_files = set(os.listdir(downloads_path)) if os.path.exists(downloads_path) else set()
        new_files = list(after_files - before_files)
        
        result_data["status"] = "success"
        result_data["downloaded_docs"] = new_files
        result_data["url_recovery"] = "cua_agent"
        
        # Update global stats
        if result.usage:
            stats["total_tokens"] += result.usage.total_tokens
            # Fallback estimation for Gemini 2.5 Flash if cost is 0
            # Approx $0.15 per 1M tokens
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
    
    # Use the actual downloaded files list from the results
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
        reader = csv.reader(f)
        for row in reader:
            if len(row) > 4:
                url = row[4].strip()
                if url.startswith("http"):
                    urls.append(url)

    if args.limit > 0:
        urls = urls[:args.limit]

    log.info(f"Loaded {len(urls)} URLs. Starting CUA experiments...")

    # Run the agent sequentially (parallelizing GUI agents requires heavy system resources)
    all_results = []
    for i, url in enumerate(urls, 1):
        log.info(f"--- Processing {i}/{len(urls)} ---")
        res = await run_cua_for_url(url, llm, headless=args.headless)
        all_results.append(res)
            
    # Print the final summary dashboard
    print_summary(all_results, use_llm=True, download_docs=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pure CUA GUI Agent for Tender Downloading")
    parser.add_argument("-i", "--input", default="publications_b.csv", help="Input CSV file")
    parser.add_argument("-n", "--limit", type=int, default=0, help="Max URLs to process (0 = all)")
    parser.add_argument("--api-key", default=None, help="OpenRouter API Key")
    parser.add_argument("--model", default="google/gemini-2.5-flash", help="LLM to drive the agent")
    parser.add_argument("--headless", action="store_true", help="Run browser in background (hidden)")
    
    args = parser.parse_args()
    asyncio.run(main(args))