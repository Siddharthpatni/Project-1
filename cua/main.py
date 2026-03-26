import asyncio
import csv
from scraper import fast_scrape, heuristic_scrape, process_url as scraper_process_url
from agent_fallback import run_agent
from config import MAX_CONCURRENT_TASKS
from tqdm import tqdm
import time
from urllib.parse import urlparse
from dotenv import load_dotenv
import os
import argparse

load_dotenv()

# Global stats tracking
stats = {
    "total_calls": 0,
    "retries": 0,
    "total_tokens": 0,
    "total_cost": 0.0,
    "model_usage": {},
    "calls_per_domain": {},
    "url_recoveries": {}
}

semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)


async def process_url(url):
    domain = urlparse(url).netloc
    start_time = time.time()
    result = {
        "url": url,
        "domain": domain,
        "status": "failed",
        "ms": 0,
        "downloaded_docs": [],
        "url_recovery": None
    }

    async with semaphore:
        try:
            from scraper import process_url as run_all_layers
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                res = await run_all_layers(browser, url)
                await browser.close()
                
            if res["status"] == "success":
                result["status"] = "success"
                result["url_recovery"] = res.get("layer")
                result["downloaded_docs"] = res.get("files", [])
                
                # Track usage
                if "usage" in res:
                    stats["total_cost"] += res["usage"]
                    stats["total_tokens"] += res.get("tokens", 0)
                    stats["total_calls"] += 1
            else:
                result["status"] = res.get("status", "failed")
        except Exception as e:
            result["status"] = "error"
            print(f"Error processing {url}: {e}")

    result["ms"] = (time.time() - start_time) * 1000
    
    # Simulate finding some docs for the demo if success
    if result["status"] == "success":
        # In a real scenario, we'd count files in the downloads folder modified recently
        # or have the scraper/agent return the count.
        pass

    return result

def print_summary(results, download_docs=True):
    t   = len(results) or 1
    ok  = sum(1 for x in results if x["status"] == "success")
    err = sum(1 for x in results if x["status"] == "error")
    
    # Count downloads from the actual downloads folder for accuracy
    downloads_dir = "downloads"
    total_docs = 0
    if os.path.exists(downloads_dir):
        total_docs = len([f for f in os.listdir(downloads_dir) if os.path.isfile(os.path.join(downloads_dir, f))])

    print(f"\n{'='*62}")
    print(f"  VERGABEPILOT.AI - CUA EXECUTION SUMMARY")
    print(f"{'='*62}")
    print(f"  Total URLs:     {t}")
    print(f"  Success:        {ok}  ({100*ok/t:.1f}%)")
    print(f"  Errors/Failed:  {t-ok}  ({100*(t-ok)/t:.1f}%)")
    print(f"  Avg Time/URL:   {sum(x['ms'] for x in results)/t:.0f}ms")
    if download_docs:
        print(f"  Total Files:    {total_docs}")
    
    # LLM Stats
    if stats["total_calls"] > 0:
        print(f"\n  LLM USAGE:")
        print(f"    Total Tokens: {stats['total_tokens']:,}")
        print(f"    Total Cost:   ${stats['total_cost']:.4f}")

    # Domain Breakdown with Success & Downloads
    dom_stats = {}
    for x in results:
        d = x["domain"]
        if d not in dom_stats:
            dom_stats[d] = {"success": 0, "total": 0, "downloads": 0}
        dom_stats[d]["total"] += 1
        if x["status"] == "success":
            dom_stats[d]["success"] += 1
        # For the per-domain download count, we'd need the scraper to report it per URL.
        # For now, we'll use a placeholder or the result docs if populated.
        dom_stats[d]["downloads"] += len(x.get("downloaded_docs", []))

    print(f"\n  DOMAIN BREAKDOWN:")
    for d, data in sorted(dom_stats.items(), key=lambda x: -x[1]["total"]):
        s = data["success"]
        tot = data["total"]
        dw = data["downloads"]
        print(f"    {d:40s} {s:3d}/{tot:<3d} ({100*s/tot:3.0f}%) | downloads: {dw:2d}")

    print(f"{'='*62}\n")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("-i", "--input", default="publications_b.csv")
    p.add_argument("-n", "--limit", type=int, default=3)
    p.add_argument("--skip-done", action="store_true", help="skip rows marked as COMPLETED")
    args = p.parse_args()

    urls = []
    
    # Look for input file in current or parent directory
    candidates = [args.input, f"../{args.input}", "publications_b.csv", "../publications_b.csv", "input.csv"]
    input_file = None
    for c in candidates:
        if os.path.exists(c):
            input_file = c
            break

    if not input_file:
        print(f"Error: No input file found. Checked: {', '.join(candidates)}")
        return

    print(f"Using input file: {input_file} (Limit: {args.limit})")
    with open(input_file) as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) > 4:
                url = row[4].strip()
                status = row[8].strip() if len(row) > 8 else ""
                
                if url.startswith("http"):
                    if args.skip_done and status == "COMPLETED":
                        continue
                    urls.append(url)
            
            if args.limit > 0 and len(urls) >= args.limit:
                break

    if not urls:
        print("No URLs found in input file.")
        return

    print(f"Starting execution for {len(urls)} URLs...")
    tasks = [process_url(url) for url in urls]

    results = []
    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
        results.append(await f)

    print_summary(results)


if __name__ == "__main__":
    asyncio.run(main())