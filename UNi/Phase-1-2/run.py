#!/usr/bin/env python3
"""
Vergabepilot – Phase 1 Runner
==============================
Reads tender URLs from a CSV, generates a scraper for each one using the LLM,
validates and runs the scraper in a sandbox, then saves the downloaded documents.

Usage:
    python run.py                        # process all URLs in INPUT_FILE
    python run.py --limit 5              # process only first 5 URLs (good for testing)
    python run.py --limit 5 --failed     # process only rows where state=FAILED
    python run.py --url "https://..."    # process a single URL directly
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Allow emoji / Unicode output on Windows terminals
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Default configuration ──────────────────────────────────────────────────────
# All settings come from environment variables (loaded from .env by generator.py
# and executor.py at import time). Override on the CLI with --input / --model.
HERE = Path(__file__).parent
CONFIG = {
    # API key MUST come from .env or the real environment — never hardcode here.
    "MODEL":      os.environ.get("LLM_MODEL", "openai/gpt-4o-mini"),
    # Default to the bundled CSV under ./data/. Override with --input <path>.
    "INPUT_FILE": str(HERE / "data" / "publications.csv"),
}

# Make sure LLM_MODEL is exported before generator/executor read it on import.
os.environ.setdefault("LLM_MODEL", CONFIG["MODEL"])

# ── Local imports (generator and executor live next to this file) ──────────────
sys.path.insert(0, str(HERE))

from generator import LLMClient, ScraperGenerator   # noqa: E402
from executor  import validate, execute              # noqa: E402

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("vergabepilot.runner")

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_RETRIES     = 3       # how many LLM regeneration attempts before giving up
OUTPUT_ROOT     = HERE / "downloads"
SCRAPERS_ROOT   = HERE / "generated_scrapers"     # saved LLM-generated scraper code
RESULTS_JSONL   = HERE / "results" / "run_results.jsonl"


# ══════════════════════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _save_attempt(
    code: str,
    row_id: str,
    domain: str,
    attempt_n: int,
    *,
    success: bool,
    model: str,
    cost_usd: float,
    error: str | None,
) -> Path:
    """
    Persist a generated scraper to disk so we can inspect what the LLM produced.

    Layout (one folder per row, one file per attempt):
        generated_scrapers/<domain>/<row_id>/attempt_<n>[_OK].py

    A header is prepended with metadata (URL, model, cost, outcome). The file
    body is still valid Python — the header is a docstring.
    """
    suffix = "_OK" if success else ""
    out_dir = SCRAPERS_ROOT / domain / row_id
    out_dir.mkdir(parents=True, exist_ok=True)
    file_path = out_dir / f"attempt_{attempt_n}{suffix}.py"

    header_lines = [
        '"""',
        f"Auto-saved scraper attempt {attempt_n}",
        f"row_id : {row_id}",
        f"domain : {domain}",
        f"model  : {model}",
        f"cost   : ${cost_usd:.6f}",
        f"status : {'SUCCESS' if success else 'FAILED'}",
    ]
    if error:
        # Keep the header parseable — escape any stray triple quotes.
        safe_err = error.replace('"""', '\\"\\"\\"')[:500]
        header_lines.append(f"error  : {safe_err}")
    header_lines.append('"""\n')
    header = "\n".join(header_lines)

    file_path.write_text(header + code, encoding="utf-8")
    return file_path


# ══════════════════════════════════════════════════════════════════════════════
#  CSV loading
# ══════════════════════════════════════════════════════════════════════════════

def load_urls(csv_path: str, failed_only: bool = False) -> list[dict]:
    """
    Read the publications CSV and return a list of row dicts.
    Columns expected: id, url, domain, state, error (others are ignored).
    """
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = row.get("url", "").strip()
            if not url:
                continue
            if failed_only and row.get("state", "").upper() != "FAILED":
                continue
            rows.append(row)
    return rows


# ══════════════════════════════════════════════════════════════════════════════
#  Core processing
# ══════════════════════════════════════════════════════════════════════════════

async def process_url(
    url: str,
    row_id: str,
    generator: ScraperGenerator,
) -> dict:
    """
    Full pipeline for one URL:
      1. Generate scraper code via LLM
      2. Validate (AST safety check)
      3. Execute in sandbox → download documents
      4. Retry with feedback if needed (up to MAX_RETRIES)

    Returns a result dict that gets written to results/run_results.jsonl.
    """
    domain = url.split("/")[2] if "/" in url else url
    save_dir = OUTPUT_ROOT / domain / row_id
    save_dir.mkdir(parents=True, exist_ok=True)

    result_base = {
        "id":         row_id,
        "url":        url,
        "domain":     domain,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "success":    False,
        "downloaded": 0,
        "files":      [],
        "scrapers":   [],     # paths of every saved attempt (success or failure)
        "cost_usd":   0.0,
        "error":      None,
    }

    attempt      = 0
    scraper_code = None
    last_error   = ""
    last_downloaded = 0
    total_cost   = 0.0

    while attempt <= MAX_RETRIES:
        attempt += 1

        # ── Step 1: Generate / regenerate scraper code ─────────────────
        try:
            if attempt == 1:
                log.info("[%s] Generating scraper (attempt 1)…", row_id[:8])
                generated = await generator.generate(url)
            else:
                log.info("[%s] Regenerating scraper (attempt %d/%d)…",
                         row_id[:8], attempt, MAX_RETRIES + 1)
                generated = await generator.regenerate(
                    url=url,
                    iteration=attempt,
                    max_iterations=MAX_RETRIES + 1,
                    outcome="execution_failed" if last_error else "insufficient_recall",
                    error=last_error,
                    expected_docs=1,
                    downloaded=last_downloaded,
                )
            scraper_code = generated.code
            total_cost  += generated.cost_usd
        except Exception as e:
            log.error("[%s] LLM call failed: %s", row_id[:8], e)
            result_base["error"] = f"LLM error: {e}"
            break

        # ── Step 2: Validate ──────────────────────────────────────────
        val = validate(scraper_code)
        if not val.ok:
            last_error = "Validation failed: " + "; ".join(val.errors)
            saved = _save_attempt(
                scraper_code, row_id, domain, attempt,
                success=False, model=generated.model,
                cost_usd=generated.cost_usd, error=last_error,
            )
            result_base["scrapers"].append(str(saved))
            log.warning("[%s] Validation failed — saved to %s", row_id[:8], saved)
            continue

        # ── Step 3: Execute in sandbox ────────────────────────────────
        exec_result = execute(scraper_code, url, keep_downloads=str(save_dir))

        last_downloaded = len(exec_result.downloaded_files)
        last_error      = exec_result.error or exec_result.stderr[:500]
        attempt_ok      = exec_result.success and last_downloaded > 0

        # Save the attempt regardless of outcome — successful ones get the _OK suffix
        saved = _save_attempt(
            scraper_code, row_id, domain, attempt,
            success=attempt_ok, model=generated.model,
            cost_usd=generated.cost_usd,
            error=None if attempt_ok else last_error,
        )
        result_base["scrapers"].append(str(saved))

        if attempt_ok:
            log.info("[%s] Downloaded %d file(s) ✓ — scraper saved to %s",
                     row_id[:8], last_downloaded, saved)
            result_base.update({
                "success":    True,
                "downloaded": last_downloaded,
                "files":      exec_result.downloaded_files,
                "cost_usd":   total_cost,
                "runtime_s":  exec_result.runtime_seconds,
            })
            return result_base

        if exec_result.timed_out:
            log.warning("[%s] Timed out — giving up", row_id[:8])
            result_base["error"] = "Sandbox timed out"
            break

        log.warning("[%s] Attempt %d failed: %s", row_id[:8], attempt,
                    (last_error or "no files downloaded")[:120])

    result_base["cost_usd"] = total_cost
    if not result_base["error"]:
        result_base["error"] = last_error or "No documents downloaded after all retries"
    return result_base


def append_result(result: dict):
    """Append one result dict to the JSONL results file."""
    RESULTS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(result, default=str) + "\n")


# ══════════════════════════════════════════════════════════════════════════════
#  Main entry point
# ══════════════════════════════════════════════════════════════════════════════

async def main(args: argparse.Namespace):
    # ── Short-circuit: list cheap models and exit ────────────────────
    if getattr(args, "list_models", False):
        _print_model_menu()
        return

    # ── Sanity checks ────────────────────────────────────────────────
    if not os.environ.get("OPENROUTER_API_KEY"):
        log.warning(
            "OPENROUTER_API_KEY is not set. The LLM client will return stub "
            "responses and no real scraping will happen. Copy .env.example "
            "to .env and add your key."
        )

    chosen_model = args.model or os.environ.get("LLM_MODEL") or CONFIG["MODEL"]
    log.info("Using model: %s", chosen_model)

    llm       = LLMClient(default_model=chosen_model)
    generator = ScraperGenerator(llm)

    # ── Build the list of (row_id, url) pairs to process ──────────────
    if args.url:
        items = [{"id": "manual", "url": args.url}]
    else:
        csv_path = args.input or CONFIG["INPUT_FILE"]
        if not Path(csv_path).is_file():
            print(
                f"Input CSV not found: {csv_path}\n"
                f"Pass one with --input <path> or place a CSV at "
                f"{CONFIG['INPUT_FILE']}.",
                file=sys.stderr,
            )
            return
        log.info("Loading URLs from: %s", csv_path)
        rows  = load_urls(csv_path, failed_only=args.failed)
        items = rows[: args.limit] if args.limit else rows
        log.info("Loaded %d URL(s) to process", len(items))

    if not items:
        print("No URLs to process — check your CSV path or --failed filter.")
        return

    # ── Process each URL ───────────────────────────────────────────────
    total   = len(items)
    success = 0
    t_start = time.time()

    for i, row in enumerate(items, 1):
        url    = row.get("url", row) if isinstance(row, dict) else row
        row_id = row.get("id", f"row-{i}") if isinstance(row, dict) else f"row-{i}"

        print(f"\n[{i}/{total}] {url}")
        result = await process_url(url, row_id, generator)
        append_result(result)

        if result["success"]:
            success += 1
            print(f"  ✅  {result['downloaded']} file(s) → {OUTPUT_ROOT / result['domain'] / row_id}")
        else:
            print(f"  ❌  {result['error']}")

    # ── Summary ────────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    print(f"\n{'═'*60}")
    print(f"  Done:     {total} URL(s) processed in {elapsed:.0f}s")
    print(f"  Success:  {success} / {total}")
    print(f"  Results:  {RESULTS_JSONL}")
    print(f"  Files:    {OUTPUT_ROOT}")
    print(f"{'═'*60}\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Vergabepilot Phase-1 Runner")
    p.add_argument("--url",    help="Process a single URL instead of the CSV")
    p.add_argument("--input",  help=f"CSV file path (default: {CONFIG['INPUT_FILE']})")
    p.add_argument("--limit",  type=int, default=None,
                   help="Max number of URLs to process (default: all)")
    p.add_argument("--failed", action="store_true",
                   help="Only process rows where state=FAILED")
    p.add_argument("--model",
                   help=("OpenRouter model id (default: $LLM_MODEL or "
                         f"{CONFIG['MODEL']!r}). Use --list-models to see "
                         "the curated cheap-model menu."))
    p.add_argument("--list-models", action="store_true",
                   help="Print the curated cheap-model menu and exit.")
    return p.parse_args()


def _print_model_menu() -> None:
    """Print the cheap-model menu so the user can pick what to run."""
    try:
        from models import CHEAP_MODELS, format_menu
    except ImportError:
        print("models.py not found — cannot list models.", file=sys.stderr)
        return
    print(format_menu(CHEAP_MODELS))


if __name__ == "__main__":
    asyncio.run(main(parse_args()))
