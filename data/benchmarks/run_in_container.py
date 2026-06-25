#!/usr/bin/env python3
"""
Robust in-container 20-domains x 5-LLMs benchmark.

Runs inside the Docker worker image (has Chromium + app code). Fixes the two
limitations that crashed the batch /api/evaluation/run task:
  * per-run HARD TIMEOUT so one auth-gated portal can't hang the whole run
  * a FRESH, short-lived DB session per insert (capture values BEFORE commit,
    close immediately) so we never sit idle-in-transaction past Postgres'
    300s limit
  * bounded self-heal iterations + modest concurrency (gentle on OpenRouter)

Each result is written as an EvaluationRun row -> shows up live on the
frontend /evaluation page. A JSONL progress log is also appended for the report.
"""
from __future__ import annotations
import asyncio, json, time, sys
from pathlib import Path

sys.path.insert(0, "/app")

from app.database import SessionLocal
from app.models import EvaluationRun
from app.core.llm_client import LLMClient
from app.phase1_llm_scraper.feedback_loop import run_feedback_loop
from app.phase1_llm_scraper.evaluator import GroundTruth

DATASET = Path("/app/data/benchmarks/bench_20_domains.jsonl")
LOG = Path("/app/data/benchmarks/run_log.jsonl")

import os
_ALL_MODELS = [
    "google/gemini-2.5-flash-lite",
    "openai/gpt-4.1-nano",
    "deepseek/deepseek-chat-v3-0324",
    "openai/gpt-4o-mini",
    "meta-llama/llama-4-maverick",
]
# Optional subset via env (comma-separated) so a run can be resumed model-by-model.
MODELS = [m.strip() for m in os.getenv("BENCH_MODELS", "").split(",") if m.strip()] or _ALL_MODELS
APPEND = os.getenv("BENCH_APPEND") == "1"
MAX_ITERS = 2
RUN_TIMEOUT = 140      # hard cap per (model,url) — well under Postgres 300s
CONCURRENCY = 3        # gentle on OpenRouter + Chromium RAM


def write_row(model, url, expected, downloaded, success, iters, runtime, cost, note):
    """Short-lived session: insert + commit + close immediately."""
    db = SessionLocal()
    try:
        db.add(EvaluationRun(
            model=model, url=url, expected_docs=expected,
            downloaded_docs=downloaded, success=success, iterations=iters,
            runtime_seconds=runtime, cost_usd=cost, notes=(note or "")[:1000],
        ))
        db.commit()
    finally:
        db.close()


async def one_run(model: str, truth: GroundTruth, sem: asyncio.Semaphore, idx: int, total: int):
    async with sem:
        t0 = time.time()
        success = False; downloaded = 0; iters = 0; cost = 0.0; note = ""
        try:
            llm = LLMClient(default_model=model)
            loop_result = await asyncio.wait_for(
                run_feedback_loop(url=truth.url, llm=llm, ground_truth=truth,
                                  model=model, max_iterations=MAX_ITERS),
                timeout=RUN_TIMEOUT,
            )
            success = loop_result.success
            iters = loop_result.iterations
            cost = loop_result.total_cost_usd
            downloaded = loop_result.metrics.downloaded_count if loop_result.metrics else 0
            note = (loop_result.final_execution.error if loop_result.final_execution else "") or ""
        except asyncio.TimeoutError:
            note = f"hard timeout >{RUN_TIMEOUT}s"
        except Exception as e:  # noqa: BLE001
            note = f"{type(e).__name__}: {e}"[:500]
        runtime = time.time() - t0

        # persist (off the event loop so concurrent runs aren't blocked)
        await asyncio.to_thread(
            write_row, model, truth.url, truth.expected_doc_count,
            downloaded, success, iters, runtime, cost, note,
        )
        rec = {"i": idx, "model": model, "domain": truth.notes, "url": truth.url,
               "success": success, "iterations": iters, "runtime_s": round(runtime, 1),
               "cost_usd": round(cost, 6), "downloaded": downloaded, "note": note[:160]}
        with open(LOG, "a") as f:
            f.write(json.dumps(rec) + "\n")
        print(f"[{idx:3d}/{total}] {('OK ' if success else 'fail')} "
              f"{model.split('/')[-1]:<26} {truth.notes:<34} "
              f"{round(runtime,1)}s it={iters} ${cost:.5f} {note[:50]}", flush=True)
        return rec


async def main():
    ds = [json.loads(l) for l in DATASET.read_text().splitlines() if l.strip()]
    truths = [GroundTruth.from_dict(d) for d in ds]
    if not APPEND:
        LOG.write_text("")  # reset progress log

    pairs = [(m, t) for m in MODELS for t in truths]
    total = len(pairs)
    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.time()
    print(f"START benchmark: {len(truths)} domains x {len(MODELS)} models = {total} runs "
          f"(max_iters={MAX_ITERS}, timeout={RUN_TIMEOUT}s, conc={CONCURRENCY})", flush=True)

    tasks = [one_run(m, t, sem, i + 1, total) for i, (m, t) in enumerate(pairs)]
    results = await asyncio.gather(*tasks)

    ok = sum(1 for r in results if r["success"])
    spend = sum(r["cost_usd"] for r in results)
    print(f"\nDONE: {ok}/{total} successful runs · spend ${spend:.4f} · "
          f"elapsed {round(time.time()-t0,1)}s", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
