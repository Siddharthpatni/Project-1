"""
evaluator.py — Benchmark LLM models on scraper generation quality.

Generates scrapers into eval_cache/{model}/ — never touches llm_cache/.
Compares success rate, token usage, and cost across models.

Usage:
    python evaluator.py publications_100_domains.csv
    python evaluator.py publications_100_domains.csv --models google/gemini-2.5-flash openai/gpt-4o
    python evaluator.py publications_100_domains.csv --limit 20
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).parent.resolve()
EVAL_CACHE_ROOT = ROOT / "eval_cache"
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT))
from classifier import classify_url
from pipeline import load_urls_from_csv, scrape_url

import llm_codegen

# OpenRouter pricing per million tokens (input, output)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "google/gemini-2.5-flash":        (0.30, 2.50),
    "google/gemini-2.5-flash-lite":   (0.075, 0.30),
    "google/gemini-2.5-pro":          (1.25, 10.00),
    "google/gemini-3.0-flash":        (0.15, 0.60),
    "openai/gpt-4o":                  (2.50, 10.00),
    "openai/gpt-4o-mini":             (0.15, 0.60),
    "openai/gpt-4.1":                 (2.00, 8.00),
    "openai/gpt-4.1-mini":            (0.40, 1.60),
    "openai/gpt-4.1-nano":            (0.10, 0.40),
    "anthropic/claude-sonnet-4":      (3.00, 15.00),
    "anthropic/claude-haiku":         (0.80, 4.00),
    "deepseek/deepseek-chat-v3-0324": (0.14, 0.28),
    "meta-llama/llama-4-maverick":    (0.20, 0.60),
}

DEFAULT_MODELS = [
    "google/gemini-2.5-flash",
]


def _calc_cost(usage: dict, model: str) -> float:
    """Calculate cost in USD from token usage."""
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)
    input_price, output_price = MODEL_PRICING.get(model, (0, 0))
    return (input_tokens * input_price + output_tokens * output_price) / 1_000_000


def _filter_llm_urls(urls: list[str]) -> list[str]:
    """Filter to only URLs that need LLM scraping (not DTVP)."""
    return [u for u in urls if classify_url(u) != "dtvp"]


def _model_cache_dir(model: str) -> Path:
    """Return eval_cache/{safe_model_name}/ path."""
    safe = model.replace("/", "_")
    return EVAL_CACHE_ROOT / safe


def run_evaluation(
    csv_path: Path,
    models: list[str],
    api_key: str,
    limit: int | None = None,
    url_column: str | None = None,
    fresh: bool = False,
) -> dict:
    """Run evaluation across all models. Returns comparison data."""

    all_urls = load_urls_from_csv(csv_path, url_column, limit)
    llm_urls = _filter_llm_urls(all_urls)

    print(f"\nTotal URLs: {len(all_urls)}")
    print(f"LLM-required URLs: {len(llm_urls)} (DTVP excluded)")
    print(f"Models to evaluate: {', '.join(models)}")
    print(f"Eval cache: {EVAL_CACHE_ROOT}\n")

    # Save original cache dir to restore later
    original_cache = llm_codegen.CACHE_DIR

    results = {}

    for model in models:
        print(f"\n{'='*60}")
        print(f"  MODEL: {model}")
        print(f"{'='*60}\n")

        # Each model gets its own cache dir under eval_cache/
        cache_dir = _model_cache_dir(model)
        if fresh and cache_dir.exists():
            shutil.rmtree(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Point llm_codegen to this model's eval cache
        llm_codegen.CACHE_DIR = cache_dir

        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = 0.0
        successes = 0
        failures = []
        url_results = []
        t_start = time.monotonic()

        for i, url in enumerate(llm_urls):
            domain = urlsplit(url).netloc
            print(f"  [{i+1:>3}/{len(llm_urls)}] {domain:<40} ", end="", flush=True)

            r = scrape_url(
                url=url,
                api_key=api_key,
                model=model,
                output_dir=ROOT / "results",
                do_download=False,
                force_regen=True,
            )

            usage = r.get("_usage", {})
            input_tok = usage.get("prompt_tokens", 0)
            output_tok = usage.get("completion_tokens", 0)
            cost = _calc_cost(usage, model)

            total_input_tokens += input_tok
            total_output_tokens += output_tok
            total_cost += cost

            doc_count = len(r.get("document_urls", []))
            ok = r["status"] == "success"
            if ok:
                successes += 1
                print(f"OK  docs={doc_count}  tokens={input_tok+output_tok}")
            else:
                failures.append({"url": url, "domain": domain, "error": r.get("error")})
                print(f"FAIL  {r['status']}")

            url_results.append({
                "url": url,
                "domain": domain,
                "status": r["status"],
                "docs": doc_count,
                "platform": r.get("platform", "unknown"),
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "cost_usd": round(cost, 6),
                "elapsed_s": r.get("elapsed_s", 0),
            })

        elapsed = time.monotonic() - t_start
        rate = round(successes / len(llm_urls) * 100, 1) if llm_urls else 0

        model_result = {
            "model": model,
            "total_urls": len(llm_urls),
            "successes": successes,
            "success_rate_pct": rate,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost_usd": round(total_cost, 4),
            "avg_cost_per_url_usd": round(total_cost / len(llm_urls), 6) if llm_urls else 0,
            "elapsed_s": round(elapsed, 1),
            "failures": failures,
            "url_results": url_results,
            "cache_dir": str(cache_dir),
        }
        results[model] = model_result

        print(f"\n  --- {model} ---")
        print(f"  Success: {successes}/{len(llm_urls)} ({rate}%)")
        print(f"  Tokens:  {total_input_tokens:,} in / {total_output_tokens:,} out")
        print(f"  Cost:    ${total_cost:.4f}")
        print(f"  Time:    {elapsed:.1f}s")
        print(f"  Cache:   {cache_dir}")

    # Restore original cache — llm_cache/ was never touched
    llm_codegen.CACHE_DIR = original_cache

    return results


def print_comparison(results: dict) -> None:
    """Print a comparison table."""
    print(f"\n\n{'='*80}")
    print(f"  MODEL COMPARISON")
    print(f"{'='*80}")
    print(f"  {'Model':<35} {'Success':>8} {'Rate':>7} {'Cost':>10} {'$/URL':>10} {'Time':>8}")
    print(f"  {'-'*35} {'-'*8} {'-'*7} {'-'*10} {'-'*10} {'-'*8}")

    for model, data in sorted(results.items(), key=lambda x: -x[1]["success_rate_pct"]):
        print(
            f"  {model:<35} "
            f"{data['successes']:>3}/{data['total_urls']:<4} "
            f"{data['success_rate_pct']:>6.1f}% "
            f"${data['total_cost_usd']:>8.4f} "
            f"${data['avg_cost_per_url_usd']:>9.6f} "
            f"{data['elapsed_s']:>7.1f}s"
        )

    print(f"{'='*80}")

    # Show which URLs each model fails on
    all_models = list(results.keys())
    if len(all_models) > 1:
        print(f"\n  FAILURE COMPARISON:")
        all_fail_urls = set()
        for data in results.values():
            for f in data["failures"]:
                all_fail_urls.add(f["url"])

        for url in sorted(all_fail_urls):
            statuses = []
            for m in all_models:
                url_data = next((u for u in results[m]["url_results"] if u["url"] == url), None)
                if url_data:
                    statuses.append("OK" if url_data["status"] == "success" else "FAIL")
                else:
                    statuses.append("--")
            domain = urlsplit(url).netloc
            print(f"    {domain:<35} {' | '.join(statuses)}")

        print(f"    {'Model legend:':<35} {' | '.join(m.split('/')[-1][:12] for m in all_models)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate LLM models for scraper generation")
    parser.add_argument("csv", type=Path, help="Input CSV with tender URLs")
    parser.add_argument("--models", nargs="+", default=DEFAULT_MODELS,
                        help="Models to evaluate (OpenRouter slugs)")
    parser.add_argument("--api-key", default=os.environ.get("OPENROUTER_API_KEY", ""),
                        help="OpenRouter API key")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max URLs to process from CSV")
    parser.add_argument("--url-column", default=None,
                        help="CSV column name for URLs")
    parser.add_argument("--output", type=Path, default=ROOT / "results",
                        help="Output directory for evaluation results")
    parser.add_argument("--fresh", action="store_true",
                        help="Delete existing eval cache for each model before running")
    args = parser.parse_args()

    if not args.api_key:
        print("ERROR: --api-key or OPENROUTER_API_KEY required")
        sys.exit(1)

    results = run_evaluation(
        csv_path=args.csv,
        models=args.models,
        api_key=args.api_key,
        limit=args.limit,
        url_column=args.url_column,
        fresh=args.fresh,
    )

    print_comparison(results)

    # Save results
    args.output.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.output / f"eval_{ts}.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nDetailed results saved to: {out_path}")


if __name__ == "__main__":
    main()
