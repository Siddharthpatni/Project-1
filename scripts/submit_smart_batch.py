#!/usr/bin/env python3
"""
Smart Domain Batch Submitter — docs/publications_28_05_2026.xlsx

Reads the publications Excel file, groups URLs by domain (max 2 per domain),
and submits a smart-domain batch job to the Vergabepilot.AI pipeline.

Strategy:
  - 1 primary URL per domain (the first URL found for that domain)
  - 1 backup URL per domain (the second URL found, if available)
  - The API auto-retries failed domains with their backup URL after the primary run

Usage:
    python scripts/submit_smart_batch.py [--api http://localhost:8000] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
EXCEL_PATH = REPO_ROOT / "docs" / "publications_28_05_2026.xlsx"


def load_domain_urls(path: Path, max_per_domain: int = 2) -> dict[str, list[str]]:
    """
    Read the Excel file and return {domain: [url1, url2?]} keeping
    max `max_per_domain` URLs per domain.
    """
    try:
        import openpyxl
    except ImportError:
        print("ERROR: openpyxl not installed. Run: pip install openpyxl")
        sys.exit(1)

    wb = openpyxl.load_workbook(str(path), read_only=True)
    ws = wb.active

    domain_urls: dict[str, list[str]] = defaultdict(list)
    skipped = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        if len(row) < 3:
            skipped += 1
            continue
        _, url, domain = row[0], row[1], row[2]
        if not url or not domain:
            skipped += 1
            continue
        url_str = str(url).strip()
        if not url_str.startswith(("http://", "https://")):
            skipped += 1
            continue
        if len(domain_urls[str(domain)]) < max_per_domain:
            domain_urls[str(domain)].append(url_str)

    wb.close()

    if skipped:
        print(f"  Skipped {skipped} rows (missing URL/domain or invalid scheme)")

    return dict(domain_urls)


def submit(api_base: str, domain_urls: dict[str, list[str]], dry_run: bool = False) -> dict:
    import urllib.request

    total_domains    = len(domain_urls)
    total_primary    = total_domains
    domains_w_backup = sum(1 for v in domain_urls.values() if len(v) >= 2)

    print(f"\n📊 Batch summary:")
    print(f"   Domains           : {total_domains}")
    print(f"   Primary URLs      : {total_primary}")
    print(f"   Backup URLs       : {domains_w_backup}")
    print(f"   Domains w/ 1 URL  : {total_domains - domains_w_backup}")

    if dry_run:
        print("\n🔍 DRY RUN — not submitting. First 5 domains:")
        for domain, urls in list(domain_urls.items())[:5]:
            print(f"   {domain}")
            for i, u in enumerate(urls, 1):
                print(f"     URL {i}: {u}")
        return {"status": "dry_run"}

    payload = json.dumps({
        "domain_urls": domain_urls,
        "submitted_by": f"script:publications_28_05_2026",
    }).encode()

    url = f"{api_base.rstrip('/')}/api/jobs/smart-domain"
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"\n🚀 Submitting to {url} …")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"ERROR {e.code}: {body[:500]}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000", help="FastAPI base URL")
    parser.add_argument("--excel", default=str(EXCEL_PATH), help="Path to Excel file")
    parser.add_argument("--dry-run", action="store_true", help="Parse only — do not submit")
    args = parser.parse_args()

    excel_path = Path(args.excel)
    if not excel_path.exists():
        print(f"ERROR: Excel file not found: {excel_path}")
        sys.exit(1)

    print(f"📂 Reading {excel_path} …")
    domain_urls = load_domain_urls(excel_path)
    print(f"✅ Loaded {len(domain_urls)} domains")

    result = submit(args.api, domain_urls, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"\n✅ Smart batch submitted!")
        print(f"   Primary job ID   : {result.get('primary_job_id', 'N/A')}")
        print(f"   Domains total    : {result.get('domains_total', 'N/A')}")
        print(f"   Domains w/ backup: {result.get('domains_with_backup', 'N/A')}")
        print(f"   Status           : {result.get('status', 'N/A')}")
        print(f"\n🔗 Monitor at: {args.api.replace(':8000','').replace('/api','')}/jobs/{result.get('primary_job_id','')}")
        print(f"   Or open: http://localhost:3000/jobs/{result.get('primary_job_id','')}")


if __name__ == "__main__":
    main()
