"""Small test scraper used to verify `executor.py` downloads.

Defines `scrape(url, output_dir)` and saves the URL contents to a file
using `urllib.request`. Returns a dict with `downloaded_files` list.
"""
from __future__ import annotations

import os
from pathlib import Path
from urllib.request import urlopen


def scrape(url: str, output_dir: str) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Name file from the URL path (fallback to 'download')
    name = os.path.basename(url.split("?")[0]) or "download"
    target = out / name

    # Download the content and write to target
    with urlopen(url) as resp, open(target, "wb") as f:
        f.write(resp.read())

    return {"downloaded_files": [str(target)]}


if __name__ == "__main__":
    # Quick local smoke test
    import sys
    if len(sys.argv) < 2:
        print("Usage: python test_scraper.py <url>")
        raise SystemExit(1)
    res = scrape(sys.argv[1], "./downloads")
    print(res)
