#!/usr/bin/env python3
"""
Vergabepilot Phase-1 · Multi-LLM Scraper Generation Benchmark
==============================================================
Runs the full Phase-1 pipeline (generate → validate → execute → feedback-retry)
across multiple LLMs against the same set of URLs and produces:

    runs/{timestamp}/REPORT.md            — executive summary + full comparison tables
    runs/{timestamp}/full_results.json    — structured per-experiment data
    runs/{timestamp}/detailed_results.csv — one row per (model, url)
    runs/{timestamp}/{model}/{url_id}/    — per-experiment artifacts (code + downloads)

Per-experiment metrics (all mandatory):
    end_to_end_s, total_generation_s, total_execution_s,
    attempts, final_validator_ok, final_exec_ok,
    docs_downloaded, docs_unique (SHA256 content dedup),
    duplicate_count, duplicate_rate_pct, recall_pct (vs consensus ceiling),
    tokens_in, tokens_out, total_tokens, cost_usd, status

Usage
-----
    # Smoke test (1 model, 1 URL)
    python multi_llm_evaluator.py --models gemini-2.5-flash --limit 1 --max-budget 0.10

    # Full benchmark — all 8 models, 5 diverse URLs
    python multi_llm_evaluator.py --limit 5 --max-budget 5.00

    # Specific URLs
    python multi_llm_evaluator.py --urls "https://..." "https://..." --max-budget 2.00

    # Resume an interrupted run
    python multi_llm_evaluator.py --resume runs/2026-05-07_14-30-00 --max-budget 5.00

    # Dry run — plan only, no LLM calls
    python multi_llm_evaluator.py --limit 5 --max-budget 5.00 --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Point to the main backend system to use the integrated (bug-fixed) logic
backend_dir = HERE.parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.core.llm_client import LLMClient
from app.phase1_llm_scraper.generator import ScraperGenerator
from app.phase1_llm_scraper.validator import validate
from app.phase1_llm_scraper.executor import execute


# ═══════════════════════════════════════════════════════════════════════════════
#  Configuration
# ═══════════════════════════════════════════════════════════════════════════════

# All models go through OpenRouter — a unified gateway that normalises
# billing across Google, OpenAI, Anthropic, Meta-Llama, and DeepSeek.
# Model IDs use the OpenRouter namespace: "<provider>/<model-slug>".
#
# The curated menu lives in models.py; we import the paid (non-free) subset
# here. Free-tier models are excluded from benchmarking because their
# rate limits make parallel evaluation flaky. Override at runtime with --models.
try:
    from models import evaluator_models as _eval_models
    MODELS: list[dict] = _eval_models()
except ImportError:
    # Fallback: original short list, used when models.py isn't on the path.
    MODELS = [
        {"name": "gemini-2.5-flash",      "provider": "google",     "model_id": "google/gemini-2.5-flash"},
        {"name": "gemini-2.5-flash-lite", "provider": "google",     "model_id": "google/gemini-2.5-flash-lite"},
        {"name": "gemini-2.5-pro",        "provider": "google",     "model_id": "google/gemini-2.5-pro"},
        {"name": "gpt-4o-mini",           "provider": "openai",     "model_id": "openai/gpt-4o-mini"},
        {"name": "gpt-4.1-mini",          "provider": "openai",     "model_id": "openai/gpt-4.1-mini"},
        {"name": "qwen-2.5-72b",          "provider": "qwen",       "model_id": "qwen/qwen-2.5-72b-instruct"},
        {"name": "llama-3.3-70b",         "provider": "meta-llama", "model_id": "meta-llama/llama-3.3-70b-instruct"},
        {"name": "deepseek-v3",           "provider": "deepseek",   "model_id": "deepseek/deepseek-chat"},
    ]

# Per-provider concurrency caps — keeps us under rate limits.
PROVIDER_CONCURRENCY: dict[str, int] = {
    "google":     2,
    "openai":     2,
    "anthropic":  2,
    "qwen":       2,
    "meta-llama": 2,
    "deepseek":   2,
    "mistralai":  2,
    "openrouter": 2,
}

DEFAULT_INPUT_CSV = str(HERE / "data" / "publications.csv")
RUNS_ROOT         = HERE / "runs"
MAX_ATTEMPTS      = 4

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("multi_llm_eval")


# ═══════════════════════════════════════════════════════════════════════════════
#  Data structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AttemptRecord:
    """One iteration of the feedback loop for a single (model, URL) experiment."""
    attempt:         int
    generation_s:    float
    execution_s:     float
    validator_ok:    bool
    exec_ok:         bool
    docs_downloaded: int
    error:           str   = ""
    tokens_in:       int   = 0
    tokens_out:      int   = 0
    cost_usd:        float = 0.0


@dataclass
class ExperimentResult:
    """One (model, URL) cell in the full benchmark result matrix."""
    model:               str
    model_id:            str
    provider:            str
    url:                 str
    url_id:              str
    domain:              str
    timestamp:           str
    end_to_end_s:        float = 0.0
    total_generation_s:  float = 0.0
    total_execution_s:   float = 0.0
    attempts:            int   = 0
    final_validator_ok:  bool  = False
    final_exec_ok:       bool  = False
    docs_downloaded:     int   = 0
    docs_unique:         int   = 0
    duplicate_count:     int   = 0
    duplicate_rate:      float = 0.0
    recall_pct:          float = 0.0
    tokens_in:           int   = 0
    tokens_out:          int   = 0
    cost_usd:            float = 0.0
    status:              str   = "PENDING"  # SUCCESS / PARTIAL / FAILED / ERROR / SKIPPED
    error:               str   = ""
    file_hashes:         list[str] = field(default_factory=list)
    attempt_records:     list[AttemptRecord] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.tokens_in + self.tokens_out


# ═══════════════════════════════════════════════════════════════════════════════
#  SHA256 content-based duplicate detection
# ═══════════════════════════════════════════════════════════════════════════════

def hash_file(path: Path) -> str:
    """SHA256 hash of file contents; falls back to name-hash if unreadable."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return "name:" + hashlib.sha256(path.name.encode()).hexdigest()


def deduplicate(file_paths: list[str]) -> tuple[list[str], int]:
    """
    Content-deduplicate a list of file paths using SHA256.
    Returns (unique_hashes, duplicate_count).
    Files that no longer exist on disk are silently skipped.
    """
    seen: dict[str, str] = {}
    duplicates = 0
    for p in file_paths:
        path = Path(p)
        if not path.exists():
            continue
        digest = hash_file(path)
        if digest in seen:
            duplicates += 1
        else:
            seen[digest] = p
    return list(seen.keys()), duplicates


# ═══════════════════════════════════════════════════════════════════════════════
#  Single experiment runner
# ═══════════════════════════════════════════════════════════════════════════════

def _domain_from_url(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc or url[:40]
    except Exception:
        return url[:40]


async def run_experiment(
    model_cfg:    dict,
    url:          str,
    url_id:       str,
    out_dir:      Path,
    max_attempts: int,
    use_feedback: bool,
) -> ExperimentResult:
    """
    Run the full generate → validate → execute → feedback-retry loop
    for one (model, URL) pair.  Saves generated code and downloads to out_dir.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    download_dir = out_dir / "downloads"
    download_dir.mkdir(exist_ok=True)
    code_dir = out_dir / "code"
    code_dir.mkdir(exist_ok=True)

    result = ExperimentResult(
        model=model_cfg["name"],
        model_id=model_cfg["model_id"],
        provider=model_cfg.get("provider", "unknown"),
        url=url,
        url_id=url_id,
        domain=_domain_from_url(url),
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    llm       = LLMClient(default_model=model_cfg["model_id"])
    generator = ScraperGenerator(llm)

    t_start       = time.perf_counter()
    last_error    = ""
    last_downloaded = 0
    all_files: list[str] = []

    for attempt in range(1, max_attempts + 1):
        result.attempts = attempt
        rec = AttemptRecord(
            attempt=attempt, generation_s=0.0, execution_s=0.0,
            validator_ok=False, exec_ok=False, docs_downloaded=0,
        )

        # ── Generate / regenerate ─────────────────────────────────────
        gen_t0 = time.perf_counter()
        try:
            if attempt == 1:
                generated = await generator.generate(url, model=model_cfg["model_id"])
            elif use_feedback:
                outcome = "execution_failed" if last_error else "insufficient_recall"
                generated = await generator.regenerate(
                    url=url,
                    iteration=attempt,
                    max_iterations=max_attempts,
                    outcome=outcome,
                    error=last_error,
                    expected_docs=1,
                    downloaded=last_downloaded,
                    model=model_cfg["model_id"],
                )
            else:
                break   # feedback disabled — stop after first failure
        except Exception as e:
            rec.error        = f"LLM error: {e}"
            rec.generation_s = time.perf_counter() - gen_t0
            result.attempt_records.append(rec)
            result.error  = rec.error
            result.status = "ERROR"
            break

        rec.generation_s = time.perf_counter() - gen_t0
        rec.tokens_in    = generated.input_tokens
        rec.tokens_out   = generated.output_tokens
        rec.cost_usd     = generated.cost_usd

        # Persist generated code for reproducibility
        (code_dir / f"attempt_{attempt}.py").write_text(generated.code, encoding="utf-8")

        # ── Validate (AST safety check) ───────────────────────────────
        val = validate(generated.code)
        rec.validator_ok = val.ok
        if not val.ok:
            last_error = "Validation failed: " + "; ".join(val.errors)
            rec.error  = last_error
            result.attempt_records.append(rec)
            continue

        # ── Execute (sandboxed subprocess) ────────────────────────────
        exec_t0 = time.perf_counter()
        try:
            ex = execute(generated.code, url, keep_downloads=str(download_dir))
        except Exception as e:
            rec.execution_s = time.perf_counter() - exec_t0
            rec.error       = f"Executor crashed: {e}"
            last_error      = rec.error
            result.attempt_records.append(rec)
            continue

        rec.execution_s     = time.perf_counter() - exec_t0
        rec.exec_ok         = ex.success
        rec.docs_downloaded = len(ex.downloaded_files)
        last_downloaded     = rec.docs_downloaded
        last_error          = ex.error or (ex.stderr[:500] if ex.stderr else "")

        all_files.extend(ex.downloaded_files)
        result.attempt_records.append(rec)

        # Early exit if this attempt produced files successfully
        if ex.success and rec.docs_downloaded > 0:
            break

    # ── Aggregate totals ──────────────────────────────────────────────
    result.end_to_end_s       = time.perf_counter() - t_start
    result.total_generation_s = sum(r.generation_s for r in result.attempt_records)
    result.total_execution_s  = sum(r.execution_s  for r in result.attempt_records)
    result.tokens_in          = sum(r.tokens_in    for r in result.attempt_records)
    result.tokens_out         = sum(r.tokens_out   for r in result.attempt_records)
    result.cost_usd           = sum(r.cost_usd     for r in result.attempt_records)

    # Final attempt's validator/exec status
    if result.attempt_records:
        last = result.attempt_records[-1]
        result.final_validator_ok = last.validator_ok
        result.final_exec_ok      = last.exec_ok

    # ── SHA256 deduplication across all attempts ──────────────────────
    unique_hashes, dup_count   = deduplicate(all_files)
    result.file_hashes         = unique_hashes
    result.docs_downloaded     = len(all_files)
    result.docs_unique         = len(unique_hashes)
    result.duplicate_count     = dup_count
    result.duplicate_rate      = (dup_count / max(1, len(all_files))) * 100

    # ── Status classification ─────────────────────────────────────────
    if result.status == "ERROR":
        pass   # already set in the loop
    elif result.final_exec_ok and result.docs_unique > 0:
        result.status = "SUCCESS"
    elif result.docs_unique > 0:
        result.status = "PARTIAL"
    else:
        result.status = "FAILED"

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Recall computation (consensus-based)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_recall(results: list[ExperimentResult]) -> None:
    """
    For each URL, expected_docs = max(docs_unique) across all models.
    recall_pct = (docs_unique / expected_docs) × 100.

    This is a consensus proxy — the best model on each URL defines the
    ceiling.  URLs where every model downloaded 0 docs get recall 0.
    """
    ceiling: dict[str, int] = {}
    for r in results:
        ceiling[r.url] = max(ceiling.get(r.url, 0), r.docs_unique)
    for r in results:
        expected = ceiling.get(r.url, 0)
        r.recall_pct = (r.docs_unique / expected * 100) if expected > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════════════
#  CSV / URL loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_urls(csv_path: str, limit: Optional[int]) -> list[dict]:
    """Load URLs from CSV, skipping rows with empty or UNSUPPORTED state."""
    rows: list[dict] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url   = (row.get("url")   or "").strip()
            state = (row.get("state") or "").strip().upper()
            if not url or state == "UNSUPPORTED":
                continue
            rows.append({
                "id":  row.get("id", f"row-{len(rows)}"),
                "url": url,
            })
            if limit and len(rows) >= limit:
                break
    return rows


def select_diverse_urls(csv_path: str, count: int) -> list[dict]:
    """
    Select `count` URLs that cover different domains for maximum diversity.
    Reads the entire CSV and picks the first URL from each unique domain,
    stopping once `count` is reached.
    """
    from urllib.parse import urlparse
    seen_domains: set[str] = set()
    selected: list[dict]   = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url   = (row.get("url")   or "").strip()
            state = (row.get("state") or "").strip().upper()
            if not url or state == "UNSUPPORTED":
                continue
            domain = urlparse(url).netloc
            if domain and domain not in seen_domains:
                seen_domains.add(domain)
                selected.append({"id": row.get("id", f"div-{len(selected)}"), "url": url})
                if len(selected) >= count:
                    break
    return selected


# ═══════════════════════════════════════════════════════════════════════════════
#  Benchmark orchestrator
# ═══════════════════════════════════════════════════════════════════════════════

async def run_benchmark(
    models:       list[dict],
    urls:         list[dict],
    run_dir:      Path,
    max_attempts: int,
    max_budget:   float,
    use_feedback: bool,
) -> list[ExperimentResult]:
    """
    Run all (model × URL) experiments concurrently, bounded by per-provider
    semaphores and a global USD budget cap.
    """
    semaphores: dict[str, asyncio.Semaphore] = {
        provider: asyncio.Semaphore(n)
        for provider, n in PROVIDER_CONCURRENCY.items()
    }

    results:    list[ExperimentResult] = []
    spent_usd   = 0.0
    completed   = 0
    total       = len(models) * len(urls)
    lock        = asyncio.Lock()

    async def one(model_cfg: dict, url_row: dict) -> ExperimentResult:
        nonlocal spent_usd, completed
        provider = model_cfg.get("provider", model_cfg["model_id"].split("/")[0])
        sem      = semaphores.setdefault(provider, asyncio.Semaphore(2))

        async with sem:
            async with lock:
                over_budget = spent_usd >= max_budget

            if over_budget:
                return ExperimentResult(
                    model=model_cfg["name"],
                    model_id=model_cfg["model_id"],
                    provider=model_cfg.get("provider", "unknown"),
                    url=url_row["url"],
                    url_id=url_row["id"],
                    domain=_domain_from_url(url_row["url"]),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    status="SKIPPED",
                    error=f"Budget cap ${max_budget:.2f} reached",
                )

            out_dir = run_dir / model_cfg["name"] / url_row["id"]
            async with lock:
                idx = completed + 1
            log.info("[%s | %.8s] starting (%d/%d, spent $%.4f)",
                     model_cfg["name"], url_row["id"], idx, total, spent_usd)

            r = await run_experiment(
                model_cfg, url_row["url"], url_row["id"],
                out_dir, max_attempts, use_feedback,
            )

            async with lock:
                spent_usd += r.cost_usd
                completed  += 1

            log.info("[%s | %.8s] %s — %d files (%d unique), %.1fs, $%.4f",
                     r.model, r.url_id, r.status,
                     r.docs_downloaded, r.docs_unique, r.end_to_end_s, r.cost_usd)
            return r

    tasks = [one(m, u) for m in models for u in urls]
    for fut in asyncio.as_completed(tasks):
        results.append(await fut)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
#  Report serialisation helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _serialize(r: ExperimentResult) -> dict:
    d = asdict(r)
    d["attempt_records"] = [asdict(a) for a in r.attempt_records]
    d["total_tokens"]    = r.total_tokens
    return d


def write_full_json(results: list[ExperimentResult], path: Path) -> None:
    payload = {
        "schema_version":   "2.0",
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "total_experiments": len(results),
        "experiments":      [_serialize(r) for r in results],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def write_detailed_csv(results: list[ExperimentResult], path: Path) -> None:
    cols = [
        "model", "provider", "url_id", "url", "domain", "status",
        "attempts", "end_to_end_s", "total_generation_s", "total_execution_s",
        "docs_downloaded", "docs_unique", "duplicate_count", "duplicate_rate",
        "recall_pct", "final_validator_ok", "final_exec_ok",
        "tokens_in", "tokens_out", "total_tokens", "cost_usd", "error",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in results:
            row = []
            for c in cols:
                if c == "total_tokens":
                    row.append(r.total_tokens)
                else:
                    row.append(getattr(r, c, ""))
            w.writerow(row)


# ═══════════════════════════════════════════════════════════════════════════════
#  Publication-ready Markdown report
# ═══════════════════════════════════════════════════════════════════════════════

def _medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")


def _status_icon(status: str) -> str:
    return {"SUCCESS": "✅", "PARTIAL": "⚠️", "FAILED": "❌", "ERROR": "💥", "SKIPPED": "⏭️"}.get(status, "❓")


def write_markdown_report(
    results: list[ExperimentResult],
    path:    Path,
    urls:    list[dict],
    models:  list[dict],
    run_dir: Path,
) -> None:
    """
    Write a publication-ready executive benchmark report in Markdown.
    Sections:
      0. Header & metadata
      1. TL;DR — Executive summary
      2. Model leaderboard
      3. Cost-efficiency analysis
      4. Speed & latency analysis
      5. URL / domain analysis
      6. Per-experiment detail matrix
      7. Failure analysis
      8. Deep insights & recommendations
    """
    now = datetime.now(timezone.utc)

    # ── Aggregate stats per model ─────────────────────────────────────
    per_model: dict[str, dict] = {}
    for m in models:
        rs = [r for r in results if r.model == m["name"]]
        if not rs:
            continue
        succ     = sum(1 for r in rs if r.status == "SUCCESS")
        partial  = sum(1 for r in rs if r.status == "PARTIAL")
        failed   = sum(1 for r in rs if r.status in ("FAILED", "ERROR"))
        skipped  = sum(1 for r in rs if r.status == "SKIPPED")
        n_active = max(1, len(rs) - skipped)
        per_model[m["name"]] = {
            "provider":        m.get("provider", "?"),
            "model_id":        m["model_id"],
            "n":               len(rs),
            "success":         succ,
            "partial":         partial,
            "failed":          failed,
            "skipped":         skipped,
            "success_rate":    succ    / n_active * 100,
            "partial_rate":    partial / n_active * 100,
            "avg_recall":      sum(r.recall_pct        for r in rs) / n_active,
            "docs_unique":     sum(r.docs_unique        for r in rs),
            "dup_count":       sum(r.duplicate_count   for r in rs),
            "avg_e2e_s":       sum(r.end_to_end_s      for r in rs) / n_active,
            "avg_gen_s":       sum(r.total_generation_s for r in rs) / n_active,
            "avg_exec_s":      sum(r.total_execution_s  for r in rs) / n_active,
            "avg_attempts":    sum(r.attempts           for r in rs) / n_active,
            "total_cost":      sum(r.cost_usd           for r in rs),
            "tokens_in":       sum(r.tokens_in          for r in rs),
            "tokens_out":      sum(r.tokens_out         for r in rs),
            "total_tokens":    sum(r.total_tokens       for r in rs),
            "cost_per_succ":   sum(r.cost_usd for r in rs) / max(1, succ),
            "cost_per_doc":    sum(r.cost_usd for r in rs) / max(1, sum(r.docs_unique for r in rs)),
        }

    ranked = sorted(
        per_model.items(),
        key=lambda kv: (
            -kv[1]["success_rate"],
            -kv[1]["avg_recall"],
             kv[1]["avg_e2e_s"],
        ),
    )

    # ── Aggregate stats per URL ───────────────────────────────────────
    per_url: dict[str, dict] = {}
    for u in urls:
        rs = [r for r in results if r.url == u["url"]]
        if not rs:
            continue
        succ = sum(1 for r in rs if r.status == "SUCCESS")
        ceiling = max((r.docs_unique for r in rs), default=0)
        best = max(rs, key=lambda r: (r.docs_unique, r.recall_pct), default=None)
        per_url[u["url"]] = {
            "id":         u["id"],
            "domain":     _domain_from_url(u["url"]),
            "n":          len(rs),
            "success":    succ,
            "ceiling":    ceiling,
            "avg_recall": sum(r.recall_pct for r in rs) / max(1, len(rs)),
            "best_model": best.model if best else "—",
        }

    # ── Global stats ──────────────────────────────────────────────────
    total_exp       = len(results)
    total_success   = sum(1 for r in results if r.status == "SUCCESS")
    total_partial   = sum(1 for r in results if r.status == "PARTIAL")
    total_failed    = sum(1 for r in results if r.status in ("FAILED", "ERROR"))
    total_skipped   = sum(1 for r in results if r.status == "SKIPPED")
    total_cost      = sum(r.cost_usd           for r in results)
    total_wall      = sum(r.end_to_end_s        for r in results)
    total_docs      = sum(r.docs_unique         for r in results)
    total_dups      = sum(r.duplicate_count     for r in results)
    total_tokens    = sum(r.total_tokens        for r in results)
    overall_recall  = (sum(r.recall_pct for r in results) / max(1, total_exp))

    winner_name   = ranked[0][0]  if ranked else "—"
    winner_succ   = ranked[0][1]["success_rate"] if ranked else 0
    cheapest_e    = min(
        (kv for kv in ranked if kv[1]["success"] > 0),
        key=lambda kv: kv[1]["cost_per_succ"],
        default=None,
    )
    fastest_e     = min(per_model.items(), key=lambda kv: kv[1]["avg_e2e_s"]) if per_model else None
    best_recall_e = max(per_model.items(), key=lambda kv: kv[1]["avg_recall"]) if per_model else None

    lines: list[str] = []

    # ── 0. Header ─────────────────────────────────────────────────────
    lines += [
        "# Vergabepilot Phase-1 · Multi-LLM Scraper Benchmark",
        "",
        f"> **Run:** `{run_dir.name}`  |  "
        f"**Generated:** `{now.strftime('%Y-%m-%d %H:%M UTC')}`  |  "
        f"**Scope:** {len(per_model)} models × {len(urls)} URLs · "
        f"{total_exp} experiments",
        "",
        "---",
        "",
    ]

    # ── 1. TL;DR — Executive Summary ──────────────────────────────────
    lines += [
        "## 1 · TL;DR — Executive Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **Overall success rate** | {total_success}/{total_exp - total_skipped} ({total_success / max(1, total_exp - total_skipped) * 100:.0f}%) |",
        f"| **Partial (docs but error)** | {total_partial} |",
        f"| **Skipped (budget cap)** | {total_skipped} |",
        f"| **Best model (success rate)** | `{winner_name}` ({winner_succ:.0f}%) |",
        f"| **Cheapest per success** | `{cheapest_e[0] if cheapest_e else '—'}` (${cheapest_e[1]['cost_per_succ']:.4f}/success) |" if cheapest_e else "| **Cheapest per success** | — |",
        f"| **Fastest (avg E2E)** | `{fastest_e[0] if fastest_e else '—'}` ({fastest_e[1]['avg_e2e_s']:.1f}s) |" if fastest_e else "| **Fastest (avg E2E)** | — |",
        f"| **Best recall** | `{best_recall_e[0] if best_recall_e else '—'}` ({best_recall_e[1]['avg_recall']:.0f}%) |" if best_recall_e else "| **Best recall** | — |",
        f"| **Total unique documents** | {total_docs} |",
        f"| **Total duplicate files** | {total_dups} |",
        f"| **Overall avg recall** | {overall_recall:.1f}% |",
        f"| **Total tokens consumed** | {total_tokens:,} |",
        f"| **Total cost** | ${total_cost:.4f} |",
        f"| **Total wall time** | {total_wall:.0f}s ({total_wall / 60:.1f} min) |",
        "",
    ]

    # Key findings bullets
    lines.append("**Key Findings:**")
    lines.append("")
    if ranked:
        lines.append(f"- The **best model** overall is `{winner_name}` ({winner_succ:.0f}% success rate, "
                     f"{ranked[0][1]['avg_recall']:.0f}% avg recall, "
                     f"${ranked[0][1]['total_cost']:.4f} total cost).")
    if cheapest_e:
        lines.append(f"- **Most cost-efficient** successful model: `{cheapest_e[0]}` at "
                     f"${cheapest_e[1]['cost_per_succ']:.4f} per successful scrape.")
    if fastest_e:
        lines.append(f"- **Fastest** model end-to-end: `{fastest_e[0]}` averaging "
                     f"{fastest_e[1]['avg_e2e_s']:.1f}s (generation + execution).")
    if total_dups > 0:
        lines.append(f"- SHA256 deduplication eliminated **{total_dups} duplicate file(s)** "
                     f"({total_dups / max(1, total_docs + total_dups) * 100:.0f}% dup rate) "
                     f"across all {total_exp} experiments.")
    if total_failed > 0:
        lines.append(f"- **{total_failed} experiments** ended in FAILED/ERROR — see §7 for root-cause breakdown.")

    lines += ["", "---", ""]

    # ── 2. Model Leaderboard ──────────────────────────────────────────
    lines += [
        "## 2 · Model Leaderboard",
        "",
        "Ranked by: success rate (desc) → avg recall (desc) → avg E2E time (asc).",
        "",
        "| Rank | Model | Provider | Succ | Part | Fail | Succ% | Avg Recall | Avg E2E | Avg Att. | Unique Docs | Dups | Total Cost | Tokens |",
        "|------|-------|----------|------|------|------|-------|------------|---------|----------|-------------|------|------------|--------|",
    ]
    for i, (name, s) in enumerate(ranked, 1):
        lines.append(
            f"| {_medal(i)} | **{name}** | {s['provider']} "
            f"| {s['success']} | {s['partial']} | {s['failed']} "
            f"| {s['success_rate']:.0f}% "
            f"| {s['avg_recall']:.0f}% "
            f"| {s['avg_e2e_s']:.1f}s "
            f"| {s['avg_attempts']:.1f} "
            f"| {s['docs_unique']} "
            f"| {s['dup_count']} "
            f"| ${s['total_cost']:.4f} "
            f"| {s['total_tokens']:,} |"
        )
    lines += ["", "---", ""]

    # ── 3. Cost-Efficiency Analysis ───────────────────────────────────
    lines += [
        "## 3 · Cost-Efficiency Analysis",
        "",
        "| Model | Total Cost | Cost / Success | Cost / Unique Doc | Input Tokens | Output Tokens | Total Tokens |",
        "|-------|-----------|----------------|-------------------|--------------|---------------|--------------|",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: kv[1]["total_cost"]):
        lines.append(
            f"| {name} "
            f"| ${s['total_cost']:.4f} "
            f"| ${s['cost_per_succ']:.4f} "
            f"| ${s['cost_per_doc']:.4f} "
            f"| {s['tokens_in']:,} "
            f"| {s['tokens_out']:,} "
            f"| {s['total_tokens']:,} |"
        )
    lines += ["", "---", ""]

    # ── 4. Speed & Latency Analysis ───────────────────────────────────
    lines += [
        "## 4 · Speed & Latency Analysis",
        "",
        "| Model | Avg E2E | Avg Generation | Avg Execution | Overhead | Avg Attempts |",
        "|-------|---------|----------------|---------------|----------|--------------|",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: kv[1]["avg_e2e_s"]):
        overhead = s["avg_e2e_s"] - s["avg_gen_s"] - s["avg_exec_s"]
        lines.append(
            f"| {name} "
            f"| {s['avg_e2e_s']:.1f}s "
            f"| {s['avg_gen_s']:.1f}s "
            f"| {s['avg_exec_s']:.1f}s "
            f"| {overhead:.1f}s "
            f"| {s['avg_attempts']:.1f} |"
        )
    lines += ["", "---", ""]

    # ── 5. URL / Domain Analysis ──────────────────────────────────────
    lines += [
        "## 5 · URL / Domain Analysis",
        "",
        "| URL (truncated) | Domain | Succ / Total | Ceiling Docs | Avg Recall | Best Model |",
        "|-----------------|--------|--------------|--------------|------------|------------|",
    ]
    for url, us in per_url.items():
        short_url = url[:55] + ("…" if len(url) > 55 else "")
        lines.append(
            f"| `{short_url}` "
            f"| {us['domain']} "
            f"| {us['success']}/{us['n']} "
            f"| {us['ceiling']} "
            f"| {us['avg_recall']:.0f}% "
            f"| {us['best_model']} |"
        )
    lines += ["", "---", ""]

    # ── 6. Per-Experiment Detail Matrix ───────────────────────────────
    lines += [
        "## 6 · Per-Experiment Detail Matrix",
        "",
        "| Model | Domain | Status | Att. | Unique Docs | Dup% | Recall | E2E | Gen | Exec | Tokens | Cost |",
        "|-------|--------|--------|------|-------------|------|--------|-----|-----|------|--------|------|",
    ]
    for r in sorted(results, key=lambda x: (x.url_id, x.model)):
        icon = _status_icon(r.status)
        lines.append(
            f"| {r.model} "
            f"| {r.domain[:25]} "
            f"| {icon} {r.status} "
            f"| {r.attempts} "
            f"| {r.docs_unique} "
            f"| {r.duplicate_rate:.0f}% "
            f"| {r.recall_pct:.0f}% "
            f"| {r.end_to_end_s:.1f}s "
            f"| {r.total_generation_s:.1f}s "
            f"| {r.total_execution_s:.1f}s "
            f"| {r.total_tokens:,} "
            f"| ${r.cost_usd:.4f} |"
        )
    lines += ["", "---", ""]

    # ── 7. Failure Analysis ───────────────────────────────────────────
    failures = [r for r in results if r.status in ("FAILED", "ERROR")]
    lines += ["## 7 · Failure Analysis", ""]
    if not failures:
        lines.append("No failures recorded in this run. 🎉")
    else:
        lines.append(f"**{len(failures)} / {total_exp}** experiments ended in FAILED or ERROR.")
        lines.append("")

        # By model
        lines.append("### Failure count by model")
        lines.append("")
        lines.append("| Model | FAILED | ERROR |")
        lines.append("|-------|--------|-------|")
        for name in [m["name"] for m in models]:
            rs_m  = [r for r in failures if r.model == name]
            n_f   = sum(1 for r in rs_m if r.status == "FAILED")
            n_e   = sum(1 for r in rs_m if r.status == "ERROR")
            if rs_m:
                lines.append(f"| {name} | {n_f} | {n_e} |")
        lines.append("")

        # Root causes
        lines.append("### Root causes (deduplicated)")
        lines.append("")
        by_reason: dict[str, int] = {}
        for r in failures:
            key = (r.error or "Unknown — 0 docs downloaded")[:100]
            by_reason[key] = by_reason.get(key, 0) + 1
        for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
            lines.append(f"- ({n}×) `{reason}`")

        # Attempt distribution of failures
        lines.append("")
        lines.append("### Validator pass / exec success in failed experiments")
        lines.append("")
        lines.append("| Model | URL | Val OK | Exec OK | Attempts | First error |")
        lines.append("|-------|-----|--------|---------|----------|-------------|")
        for r in failures:
            short_url = r.url[:40] + ("…" if len(r.url) > 40 else "")
            first_err = ""
            if r.attempt_records:
                first_err = (r.attempt_records[0].error or "")[:60]
            lines.append(
                f"| {r.model} | `{short_url}` "
                f"| {'✓' if r.final_validator_ok else '✗'} "
                f"| {'✓' if r.final_exec_ok else '✗'} "
                f"| {r.attempts} "
                f"| `{first_err}` |"
            )

    lines += ["", "---", ""]

    # ── 8. Deep Insights & Recommendations ───────────────────────────
    lines += [
        "## 8 · Deep Insights & Recommendations",
        "",
    ]

    # 8.1 Model recommendations
    lines += [
        "### 8.1 Model Recommendations by Use Case",
        "",
    ]
    if ranked:
        # Best overall
        best = ranked[0]
        lines.append(f"**Best overall:** `{best[0]}` — {best[1]['success_rate']:.0f}% success rate, "
                     f"{best[1]['avg_recall']:.0f}% recall, ${best[1]['total_cost']:.4f} total cost. "
                     f"Recommended for production workloads where reliability matters most.")
        lines.append("")

        # Best value
        if cheapest_e:
            lines.append(f"**Best value / low-cost scraping:** `{cheapest_e[0]}` — "
                         f"${cheapest_e[1]['cost_per_succ']:.4f} per successful scrape. "
                         f"Recommended for high-volume runs with tight budgets.")
            lines.append("")

        # Fastest
        if fastest_e:
            lines.append(f"**Fastest time-to-result:** `{fastest_e[0]}` — "
                         f"{fastest_e[1]['avg_e2e_s']:.1f}s average end-to-end. "
                         f"Recommended for latency-sensitive or interactive use cases.")
            lines.append("")

        # Best recall
        if best_recall_e:
            lines.append(f"**Highest document recall:** `{best_recall_e[0]}` — "
                         f"{best_recall_e[1]['avg_recall']:.0f}% avg recall. "
                         f"Recommended when completeness of document coverage is the priority.")
            lines.append("")

    # 8.2 Duplicate detection findings
    lines += ["### 8.2 SHA256 Duplicate Detection Findings", ""]
    high_dup = [r for r in results if r.duplicate_rate > 30 and r.docs_downloaded > 1]
    if high_dup:
        lines.append(f"**{len(high_dup)} experiment(s)** had a duplicate rate above 30%, "
                     f"meaning models downloaded the same file multiple times within a single run. "
                     f"This is usually caused by clicking the same download link during page exploration "
                     f"and across retry attempts. SHA256 deduplication correctly collapses these.")
        for r in high_dup:
            lines.append(f"  - `{r.model}` on `{r.domain}`: "
                         f"{r.docs_downloaded} downloaded → {r.docs_unique} unique "
                         f"({r.duplicate_rate:.0f}% dup rate)")
    else:
        lines.append("No significant duplicate rates detected (all experiments below 30%). "
                     "Document deduplication was clean across the board.")
    lines.append("")

    # 8.3 Feedback loop effectiveness
    lines += ["### 8.3 Feedback Loop Effectiveness", ""]
    multi_attempt = [r for r in results if r.attempts > 1 and r.status not in ("SKIPPED",)]
    if multi_attempt:
        recovered = [r for r in multi_attempt if r.status in ("SUCCESS", "PARTIAL")]
        lines.append(f"The feedback loop triggered for **{len(multi_attempt)} / {total_exp}** experiments. "
                     f"Of these, **{len(recovered)}** ({len(recovered)/max(1,len(multi_attempt))*100:.0f}%) "
                     f"recovered to SUCCESS or PARTIAL after retrying.")
    else:
        lines.append("All experiments completed on the first attempt — the feedback loop was not triggered. "
                     "This suggests high model reliability for the tested URLs.")
    lines.append("")

    # 8.4 Concurrency & cost note
    lines += [
        "### 8.4 Cost & Concurrency Notes",
        "",
        "All experiments ran concurrently via asyncio, bounded by per-provider semaphores: "
        f"{', '.join(f'{p}={n}' for p, n in PROVIDER_CONCURRENCY.items())}. "
        "Token costs are sourced directly from OpenRouter's billed `usage.cost` field — not estimates.",
        "",
    ]

    # ── Footer ────────────────────────────────────────────────────────
    lines += [
        "---",
        "",
        f"*Generated by Vergabepilot Phase-1 Multi-LLM Benchmark Engine · "
        f"{now.strftime('%Y-%m-%d %H:%M UTC')}*",
    ]

    path.write_text("\n".join(lines), encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Vergabepilot Phase-1 · Multi-LLM Scraper Benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  # Quick smoke test
  python multi_llm_evaluator.py --models gemini-2.5-flash --limit 1 --max-budget 0.10

  # Full benchmark — all 8 models, 5 diverse URLs (one per domain)
  python multi_llm_evaluator.py --limit 5 --max-budget 5.00 --diverse

  # Specific URLs
  python multi_llm_evaluator.py --urls "https://..." "https://..." --max-budget 2.00

  # Resume an interrupted run
  python multi_llm_evaluator.py --resume runs/2026-05-07_14-30-00 --max-budget 5.00
""",
    )
    p.add_argument("--models", nargs="+", default=None,
                   help="Subset of model names to test (default: all)")
    p.add_argument("--urls", nargs="+", default=None,
                   help="Specific URLs to test (overrides --input and --limit)")
    p.add_argument("--input", default=DEFAULT_INPUT_CSV,
                   help=f"CSV file with URLs (default: {DEFAULT_INPUT_CSV})")
    p.add_argument("--limit", type=int, default=5,
                   help="Max number of URLs to test (default: 5)")
    p.add_argument("--diverse", action="store_true",
                   help="Pick one URL per unique domain (maximises coverage)")
    p.add_argument("--max-attempts", type=int, default=MAX_ATTEMPTS,
                   help=f"Max generation attempts per (model, url) (default: {MAX_ATTEMPTS})")
    p.add_argument("--max-budget", type=float, required=True,
                   help="Hard USD spending cap. Required to prevent accidental large runs.")
    p.add_argument("--no-feedback", action="store_true",
                   help="Disable feedback loop — only one generation attempt per experiment")
    p.add_argument("--dry-run", action="store_true",
                   help="Print plan and exit without calling any LLM")
    p.add_argument("--resume", default=None,
                   help="Resume an existing run directory (reuses its timestamp)")
    return p.parse_args()


async def amain() -> None:
    args = parse_args()

    # ── Model selection ──────────────────────────────────────────────
    if args.models:
        selected = [m for m in MODELS if m["name"] in args.models]
        unknown  = set(args.models) - {m["name"] for m in MODELS}
        if unknown:
            log.error("Unknown model(s): %s. Available: %s",
                      ", ".join(sorted(unknown)),
                      ", ".join(m["name"] for m in MODELS))
            sys.exit(1)
    else:
        selected = list(MODELS)

    # ── URL selection ────────────────────────────────────────────────
    if args.urls:
        urls = [{"id": f"cli-{i}", "url": u} for i, u in enumerate(args.urls)]
    else:
        csv_path = args.input
        if not Path(csv_path).is_file():
            log.error("Input CSV not found: %s", csv_path)
            sys.exit(1)
        if args.diverse:
            urls = select_diverse_urls(csv_path, args.limit)
            log.info("Diverse-URL mode: selected %d URLs covering %d unique domains.",
                     len(urls), len(urls))
        else:
            urls = load_urls(csv_path, args.limit)

    if not urls:
        log.error("No URLs to test — check your --input CSV or --urls argument.")
        sys.exit(1)

    # ── Run directory ────────────────────────────────────────────────
    if args.resume:
        run_dir = Path(args.resume)
        if not run_dir.is_dir():
            log.error("Resume directory not found: %s", run_dir)
            sys.exit(1)
    else:
        ts      = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        run_dir = RUNS_ROOT / ts
        run_dir.mkdir(parents=True, exist_ok=True)

    # ── Print plan ───────────────────────────────────────────────────
    print()
    print("═" * 68)
    print("  Vergabepilot Phase-1 · Multi-LLM Benchmark")
    print("═" * 68)
    print(f"  Run dir    : {run_dir}")
    print(f"  Models     : {', '.join(m['name'] for m in selected)}")
    print(f"  URLs       : {len(urls)}")
    print(f"  Experiments: {len(selected) * len(urls)}")
    print(f"  Max budget : ${args.max_budget:.2f}")
    print(f"  Max att.   : {args.max_attempts}")
    print(f"  Feedback   : {'OFF' if args.no_feedback else 'ON'}")
    print("═" * 68)
    for i, u in enumerate(urls, 1):
        print(f"  URL {i}: {u['url'][:70]}")
    print("═" * 68)
    print()

    if args.dry_run:
        print("[dry-run] Exiting without calling any LLM.")
        return

    # ── Execute ──────────────────────────────────────────────────────
    t0      = time.perf_counter()
    results = await run_benchmark(
        selected, urls, run_dir,
        max_attempts=args.max_attempts,
        max_budget=args.max_budget,
        use_feedback=not args.no_feedback,
    )

    # ── Recall ───────────────────────────────────────────────────────
    compute_recall(results)

    # ── Persist artifacts ─────────────────────────────────────────────
    write_full_json(results,    run_dir / "full_results.json")
    write_detailed_csv(results, run_dir / "detailed_results.csv")
    write_markdown_report(results, run_dir / "REPORT.md", urls, selected, run_dir)

    # ── Final summary ─────────────────────────────────────────────────
    elapsed = time.perf_counter() - t0
    n_succ  = sum(1 for r in results if r.status == "SUCCESS")
    n_skip  = sum(1 for r in results if r.status == "SKIPPED")
    total_c = sum(r.cost_usd for r in results)
    print()
    print("═" * 68)
    print(f"  Benchmark complete in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Successful : {n_succ}/{len(results) - n_skip}")
    print(f"  Skipped    : {n_skip} (budget cap)")
    print(f"  Total cost : ${total_c:.4f}")
    print(f"  REPORT.md  : {run_dir / 'REPORT.md'}")
    print(f"  JSON       : {run_dir / 'full_results.json'}")
    print(f"  CSV        : {run_dir / 'detailed_results.csv'}")
    print("═" * 68)
    print()


if __name__ == "__main__":
    asyncio.run(amain())
