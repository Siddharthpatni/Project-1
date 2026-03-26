import asyncio
import csv
from scraper import fast_scrape, heuristic_scrape
from agent_fallback import run_agent
from config import MAX_CONCURRENT_TASKS
from tqdm import tqdm

semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)


async def process_url(url):
    async with semaphore:
        print(f"\nProcessing: {url}")

        if await fast_scrape(url):
            print("FAST SUCCESS")
            return

        if await heuristic_scrape(url):
            print("HEURISTIC SUCCESS")
            return

        print("FALLING BACK TO AGENT...")
        await run_agent(url)


async def main():
    urls = []

    with open("input.csv") as f:
        reader = csv.reader(f)
        for row in reader:
            urls.append(row[0])

    tasks = [process_url(url) for url in urls]

    for f in tqdm(asyncio.as_completed(tasks), total=len(tasks)):
        await f


if __name__ == "__main__":
    asyncio.run(main())