"""
pipeline.py — Tender document scraping pipeline (test phase).

Reads a CSV of procurement URLs, classifies each, runs the appropriate
scraper (known platform or LLM-generated), and logs results.

Usage:
    python pipeline.py input.csv --api-key sk-or-... [options]

Options:
    --api-key KEY       OpenRouter API key (or set OPENROUTER_API_KEY env var)
    --model MODEL       OpenRouter model (default: google/gemini-flash-1.5)
    --limit N           Process only first N rows (default: all)
    --url-column NAME   CSV column name for URLs (default: auto-detect)
    --no-download       Discover URLs only, don't download files
    --output DIR        Output directory (default: ./results)
    --workers N         Parallel workers (default: 8)
    --force-regen       Ignore LLM cache, regenerate scrapers

Output:
    results/run_YYYYMMDD_HHMMSS.jsonl  — one JSON line per URL
    results/run_YYYYMMDD_HHMMSS_summary.json  — aggregated stats
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

# Per-domain lock to avoid concurrent requests to the same domain (WAF protection)
_domain_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

# Per-domain timestamp of last request — used for rate limiting
_domain_last_request: dict[str, float] = {}

# Domains that require a delay (in seconds) between requests to avoid rate limiting
_DOMAIN_RATE_LIMITS: dict[str, float] = {
    "www.evergabe.de": 5.0,
    "evergabe.de": 5.0,
}

from dotenv import load_dotenv

ROOT = Path(__file__).parent.resolve()
load_dotenv(ROOT / ".env")

# ---------------------------------------------------------------------------
# Imports from local modules
# ---------------------------------------------------------------------------
sys.path.insert(0, str(ROOT))
from classifier import classify_url, classify_html, build_dtvp_zip_url, extract_project_id
import llm_codegen


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _head_ok(url: str, timeout: int = 10) -> bool:
    """Return True if URL responds with 2xx or 3xx."""
    try:
        req = Request(url, method="HEAD", headers={
            "User-Agent": "Mozilla/5.0 tender-scraper/1.0"
        })
        with urlopen(req, timeout=timeout) as r:
            return r.status < 400
    except Exception:
        return False


def _is_document_url(url: str, timeout: int = 10) -> bool:
    """
    Validate that a URL points to an actual document, not an HTML page.
    Returns True if the URL looks like a real file download.
    Skips validation for URLs that are clearly download endpoints.
    """
    import re as _re

    # URLs with known download function patterns — trust them
    download_patterns = [
        r"_DownloadTenderDocuments",
        r"_DownloadDocument",
        r"_DownloadAll",
        r"function=.*[Dd]ownload",
        r"DownloadTenderFiles\.ashx",
        r"DirectDocload",
    ]
    for pat in download_patterns:
        if _re.search(pat, url):
            return True

    # Wicket-based download endpoints (evergabe-online.de) — trust them
    if "zipDownloadButton" in url or "downloadAllButton" in url:
        return True

    # Cross-platform redirect URLs — these are entry points to other procurement platforms
    # returned by aggregators like had.de; they lead to documents even though they're HTML pages
    cross_platform_patterns = [
        r"subreport\.de/E\d+",
        r"subreport-elvis\.de/",
    ]
    for pat in cross_platform_patterns:
        if _re.search(pat, url):
            return True

    # Reject non-HTTP URLs (javascript:, mailto:, etc.)
    if not url.startswith("http"):
        return False

    # Reject URLs with spaces or no valid domain (broken hrefs from scraping)
    if " " in url or "." not in urlsplit(url).netloc:
        return False

    # URLs ending in known HTML extensions — reject them
    # NOTE: .php/.asp/.aspx are dynamic and may serve files (e.g. download.php), so don't reject those
    path_lower = urlsplit(url).path.lower()
    html_exts = (".html", ".htm", ".xhtml")
    if any(path_lower.endswith(ext) for ext in html_exts):
        return False

    # URLs ending in known file extensions — trust them
    file_exts = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
                 ".zip", ".rar", ".7z", ".txt", ".odt", ".ods", ".csv")
    if any(path_lower.endswith(ext) for ext in file_exts):
        return True

    # For other URLs, do a HEAD check and verify Content-Type
    try:
        req = Request(url, method="HEAD", headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
        })
        with urlopen(req, timeout=timeout) as r:
            if r.status >= 400:
                return False
            ct = (r.headers.get("Content-Type") or "").lower()
            # Reject if the response is clearly HTML
            if "text/html" in ct or "application/xhtml" in ct:
                return False
            # Accept if Content-Type indicates a file
            if any(t in ct for t in ("application/", "octet-stream", "pdf", "zip",
                                     "msword", "spreadsheet", "presentation")):
                return True
            # Accept if Content-Disposition indicates a download
            cd = r.headers.get("Content-Disposition") or ""
            if "attachment" in cd.lower() or "filename" in cd.lower():
                return True
            # Unknown content type — accept cautiously
            return True
    except Exception:
        # Can't reach URL — still return True so we don't silently drop valid URLs
        # that just happen to be behind a firewall
        return True


def _download_file(url: str, dest: Path, timeout: int = 60) -> bool:
    """Download URL to dest. Returns True on success."""
    try:
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 tender-scraper/1.0"
        })
        with urlopen(req, timeout=timeout) as r:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(r.read())
        return True
    except Exception:
        return False


def _safe_filename(url: str) -> str:
    parts = urlsplit(url)
    name = parts.path.rstrip("/").rsplit("/", 1)[-1] or "document"
    # keep only safe characters
    import re
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name[:120]


def _output_dir_for_url(base_output: Path, url: str) -> Path:
    parts = urlsplit(url)
    domain = parts.netloc.lstrip("www.")
    project_id = extract_project_id(url) or "unknown_project"
    return base_output / domain / project_id


# ---------------------------------------------------------------------------
# Scrape one URL — returns a result dict
# ---------------------------------------------------------------------------

def scrape_url(
    url: str,
    api_key: str,
    model: str,
    output_dir: Path,
    do_download: bool,
    force_regen: bool,
) -> dict:
    # Serialize requests to the same domain to avoid WAF blocks
    domain = urlsplit(url).netloc
    with _domain_locks[domain]:
        # Rate limit: wait if we hit this domain too recently
        delay = _DOMAIN_RATE_LIMITS.get(domain, 0)
        if delay > 0:
            last = _domain_last_request.get(domain, 0)
            wait = delay - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        result = _scrape_url_inner(url, api_key, model, output_dir, do_download, force_regen)
        if delay > 0:
            _domain_last_request[domain] = time.monotonic()
        return result


def _scrape_url_inner(
    url: str,
    api_key: str,
    model: str,
    output_dir: Path,
    do_download: bool,
    force_regen: bool,
) -> dict:
    t0 = time.monotonic()
    result: dict = {
        "url": url,
        "platform": "unknown",
        "status": "pending",
        "document_urls": [],
        "downloaded": [],
        "error": None,
        "elapsed_s": 0.0,
        "llm_cached": None,
        "has_download_all": False,
    }

    try:
        # ------------------------------------------------------------------ #
        # 1. Classify URL (no HTTP needed)                                    #
        # ------------------------------------------------------------------ #
        platform = classify_url(url)

        # ------------------------------------------------------------------ #
        # 2. Discover document URLs                                           #
        # ------------------------------------------------------------------ #
        doc_urls: list[str] = []

        # Try DTVP ZIP template first (instant, no HTTP needed)
        zip_url = build_dtvp_zip_url(url) if platform == "dtvp" else None
        if zip_url:
            result["platform"] = "dtvp"
            doc_urls = [zip_url]
            result["has_download_all"] = True
        else:
            # Not DTVP or no project ID — fetch HTML and try classification + LLM
            html = None

            # Fetch HTML for classification/LLM
            html = llm_codegen._fetch_html(url)
            if html:
                html_platform = classify_html(url, html)
                # Only trust HTML classification if it found a specific platform
                if html_platform != "unknown":
                    platform = html_platform
                # Re-check: HTML classification might reveal DTVP
                zip_url = build_dtvp_zip_url(url) if platform == "dtvp" else None
                if zip_url:
                    result["platform"] = "dtvp"
                    doc_urls = [zip_url]
                    result["has_download_all"] = True

            # If still no docs, fall through to LLM (even if classified as dtvp but no project ID)
            if not doc_urls and api_key:
                result["platform"] = platform
                llm_result = llm_codegen.generate_and_run(
                    url, api_key=api_key, model=model,
                    force_regenerate=force_regen, html=html or None
                )
                result["llm_cached"] = llm_result["cached"]
                result["has_download_all"] = llm_result.get("has_download_all", False)
                result["_usage"] = llm_result.get("usage", {})
                if llm_result["platform_guess"] != "unknown":
                    result["platform"] = llm_result["platform_guess"]
                if llm_result["error"]:
                    result["error"] = llm_result["error"]
                doc_urls = llm_result["urls"]

                # Auto-retry: if cached scraper found nothing, regenerate once
                if not doc_urls and llm_result["cached"] and not force_regen:
                    result["_retry_regen"] = True
                    llm_result = llm_codegen.generate_and_run(
                        url, api_key=api_key, model=model,
                        force_regenerate=True, html=html or None
                    )
                    result["llm_cached"] = False
                    result["has_download_all"] = llm_result.get("has_download_all", False)
                    result["_usage"] = llm_result.get("usage", {})
                    if llm_result["platform_guess"] != "unknown":
                        result["platform"] = llm_result["platform_guess"]
                    result["error"] = llm_result["error"]
                    doc_urls = llm_result["urls"]
            elif not doc_urls:
                result["platform"] = platform
                result["error"] = "no_api_key_for_llm_scraper"

        # ------------------------------------------------------------------ #
        # 2b. Validate discovered URLs (filter false positives)              #
        # ------------------------------------------------------------------ #
        if doc_urls and result["platform"] != "dtvp":
            # DTVP URLs are deterministic templates — skip validation
            validated = [u for u in doc_urls if _is_document_url(u)]
            if len(validated) < len(doc_urls):
                rejected = len(doc_urls) - len(validated)
                result["_rejected_urls"] = rejected
            doc_urls = validated

        result["document_urls"] = doc_urls

        # ------------------------------------------------------------------ #
        # 3. Optionally download                                              #
        # ------------------------------------------------------------------ #
        if do_download and doc_urls:
            dest_dir = _output_dir_for_url(output_dir, url)
            downloaded = []
            for du in doc_urls:
                fname = _safe_filename(du)
                dest = dest_dir / fname
                if _download_file(du, dest):
                    downloaded.append(str(dest.relative_to(output_dir)))
            result["downloaded"] = downloaded

        # ------------------------------------------------------------------ #
        # 4. Status                                                           #
        # ------------------------------------------------------------------ #
        if doc_urls:
            result["status"] = "success"
        elif result["error"]:
            result["status"] = "error"
        else:
            result["status"] = "no_documents"

    except Exception as exc:
        result["status"] = "exception"
        result["error"] = str(exc)

    result["elapsed_s"] = round(time.monotonic() - t0, 2)
    return result


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_urls_from_csv(path: Path, url_column: str | None, limit: int | None) -> list[str]:
    urls: list[str] = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        # Sniff delimiter
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(f, dialect=dialect)
        headers = reader.fieldnames or []

        # Auto-detect URL column
        if url_column is None:
            candidates = [h for h in headers if h.lower() in
                          ("url", "urls", "link", "links", "tender_url", "site", "address")]
            if candidates:
                url_column = candidates[0]
            elif headers:
                url_column = headers[0]  # fallback: first column
            else:
                raise ValueError("CSV has no headers — pass --url-column explicitly")

        print(f"  Using CSV column: '{url_column}'")

        for row in reader:
            val = (row.get(url_column) or "").strip()
            if val and val.startswith("http"):
                urls.append(val)
            if limit and len(urls) >= limit:
                break

    return urls


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def _print_summary(results: list[dict], elapsed_total: float) -> dict:
    total = len(results)
    by_status: dict[str, int] = {}
    by_platform: dict[str, int] = {}
    llm_calls = 0
    llm_cached = 0

    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_platform[r["platform"]] = by_platform.get(r["platform"], 0) + 1
        if r["llm_cached"] is not None:
            if r["llm_cached"]:
                llm_cached += 1
            else:
                llm_calls += 1

    success = by_status.get("success", 0)
    rate = round(success / total * 100, 1) if total else 0

    print("\n" + "=" * 60)
    print(f"  RESULTS  ({total} URLs, {round(elapsed_total, 1)}s)")
    print("=" * 60)
    print(f"  Success rate:  {success}/{total}  ({rate}%)")
    print(f"\n  By status:")
    for s, n in sorted(by_status.items()):
        print(f"    {s:<20} {n}")
    print(f"\n  By platform:")
    for p, n in sorted(by_platform.items(), key=lambda x: -x[1]):
        print(f"    {p:<25} {n}")
    print(f"\n  LLM calls (new):    {llm_calls}")
    print(f"  LLM calls (cached): {llm_cached}")
    print("=" * 60)

    return {
        "total": total,
        "success": success,
        "success_rate_pct": rate,
        "elapsed_total_s": round(elapsed_total, 1),
        "by_status": by_status,
        "by_platform": by_platform,
        "llm_new_calls": llm_calls,
        "llm_cached_calls": llm_cached,
    }


# ---------------------------------------------------------------------------
# Seeds export
# ---------------------------------------------------------------------------

def _export_seeds(results: list[dict], seeds_file: Path) -> None:
    """
    Append successfully discovered source URLs to a seeds.canonical.txt.

    For each successful result we write the *original tender page URL*
    (not the document URL) so that Browsertrix can crawl the full page
    and capture all linked documents in context.

    Already-present URLs are not duplicated.
    """
    # Load existing seeds to avoid duplicates
    existing: set[str] = set()
    if seeds_file.exists():
        for line in seeds_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("http"):
                existing.add(line)

    # Collect new successful URLs grouped by domain
    by_domain: dict[str, list[str]] = {}
    for r in results:
        if r["status"] != "success":
            continue
        url = r["url"]
        if url in existing:
            continue
        domain = urlsplit(url).netloc
        by_domain.setdefault(domain, []).append(url)

    if not by_domain:
        print("\nExport seeds: nothing new to add.")
        return

    lines: list[str] = [
        "",
        f"# Exported by TenderScraper — {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    ]
    for domain in sorted(by_domain):
        lines.append(f"\n# {domain}")
        for url in by_domain[domain]:
            lines.append(url)

    with open(seeds_file, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    total_new = sum(len(v) for v in by_domain.values())
    print(f"\nExport seeds: {total_new} new URL(s) appended to {seeds_file}")
    for domain, urls in sorted(by_domain.items()):
        print(f"  {domain}: {len(urls)} URL(s)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Tender document scraping pipeline")
    parser.add_argument("csv", type=Path, help="Input CSV file with tender URLs")
    parser.add_argument("--api-key", default=os.environ.get("OPENROUTER_API_KEY", ""),
                        help="OpenRouter API key")
    parser.add_argument("--model", default="google/gemini-2.5-flash",
                        help="OpenRouter model slug")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max URLs to process")
    parser.add_argument("--url-column", default=None,
                        help="CSV column name containing URLs")
    parser.add_argument("--no-download", action="store_true",
                        help="Discover URLs only, skip downloading files")
    parser.add_argument("--output", type=Path, default=ROOT / "results",
                        help="Output directory")
    parser.add_argument("--workers", type=int, default=8,
                        help="Parallel worker threads")
    parser.add_argument("--force-regen", action="store_true",
                        help="Ignore LLM cache, regenerate scrapers")
    parser.add_argument("--cache-dir", type=Path, default=None,
                        help="Use a custom LLM cache directory (default: llm_cache/)")
    parser.add_argument("--export-seeds", type=Path, default=None,
                        metavar="SEEDS_FILE",
                        help="Append successfully discovered source URLs to a "
                             "seeds.canonical.txt file (e.g. for webArchive)")
    args = parser.parse_args()

    if args.cache_dir:
        llm_codegen.CACHE_DIR = args.cache_dir
        print(f"Using custom cache: {args.cache_dir}")

    if not args.api_key:
        print("ERROR: --api-key or OPENROUTER_API_KEY env var required for unknown platforms")
        # Don't exit — DTVP sites work without it

    # Load URLs
    print(f"\nLoading URLs from {args.csv} ...")
    try:
        urls = load_urls_from_csv(args.csv, args.url_column, args.limit)
    except Exception as e:
        print(f"ERROR reading CSV: {e}")
        sys.exit(1)

    print(f"  Loaded {len(urls)} URLs")
    if not urls:
        print("No URLs found. Check --url-column or CSV format.")
        sys.exit(1)

    # Prepare output
    run_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    args.output.mkdir(parents=True, exist_ok=True)
    jsonl_path = args.output / f"run_{run_ts}.jsonl"
    summary_path = args.output / f"run_{run_ts}_summary.json"

    print(f"\nProcessing {len(urls)} URLs with {args.workers} workers ...")
    print(f"Output: {jsonl_path}\n")

    results: list[dict] = []
    t_start = time.monotonic()

    with open(jsonl_path, "w", encoding="utf-8") as out_f:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {
                pool.submit(
                    scrape_url,
                    url=u,
                    api_key=args.api_key,
                    model=args.model,
                    output_dir=args.output,
                    do_download=not args.no_download,
                    force_regen=args.force_regen,
                ): u
                for u in urls
            }

            done = 0
            for future in as_completed(futures):
                done += 1
                r = future.result()
                results.append(r)
                out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
                out_f.flush()

                icon = "OK" if r["status"] == "success" else "FAIL"
                doc_count = len(r["document_urls"])
                print(
                    f"  [{done:>3}/{len(urls)}] {icon} "
                    f"{r['status']:<14} "
                    f"docs={doc_count:<3} "
                    f"platform={r['platform']:<20} "
                    f"{r['url'][:70]}"
                )

    elapsed = time.monotonic() - t_start
    summary = _print_summary(results, elapsed)

    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nSummary saved to: {summary_path}")

    if args.export_seeds:
        _export_seeds(results, args.export_seeds)


if __name__ == "__main__":
    main()
