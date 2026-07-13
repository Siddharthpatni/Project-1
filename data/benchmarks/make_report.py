#!/usr/bin/env python3
"""
Build the 20-domains x 5-LLMs benchmark report from EvaluationRun rows.

Pulls the newest 100 evaluation_runs rows from Postgres (via docker compose
exec), isolates this benchmark (our 20 URLs x 5 models), and writes:
  - benchmark_report.md   (documented results)
  - benchmark_runs.csv    (all 100 runs)
  - benchmark_runs.json   (raw rows)
"""
from __future__ import annotations
import csv, json, subprocess, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
DATASET = HERE / "bench_20_domains.jsonl"

MODELS = [
    "google/gemini-2.5-flash-lite",
    "openai/gpt-4.1-nano",
    "deepseek/deepseek-chat-v3-0324",
    "openai/gpt-4o-mini",
    "meta-llama/llama-4-maverick",
]
# OpenRouter list price per 1M tokens (input, output) — for reference column.
PRICE = {
    "google/gemini-2.5-flash-lite":   (0.075, 0.30),
    "openai/gpt-4.1-nano":            (0.10, 0.40),
    "deepseek/deepseek-chat-v3-0324": (0.14, 0.28),
    "openai/gpt-4o-mini":             (0.15, 0.60),
    "meta-llama/llama-4-maverick":    (0.20, 0.60),
}


def short(m: str) -> str:
    return m.split("/")[-1]


def fetch_rows(limit: int = 100) -> list[dict]:
    sql = (
        "SELECT json_agg(t) FROM (SELECT model, url, success, iterations, "
        "runtime_seconds, cost_usd, downloaded_docs, coalesce(notes,'') AS note, "
        "created_at FROM evaluation_runs ORDER BY created_at DESC LIMIT %d) t;" % limit
    )
    cmd = ["docker", "compose", "exec", "-T", "postgres", "sh", "-c",
           f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -c "{sql}"']
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE.parents[1])
    if out.returncode != 0:
        sys.exit(f"psql failed: {out.stderr[:500]}")
    return json.loads(out.stdout.strip())


def main() -> None:
    # dataset order (domain per url)
    ds = [json.loads(l) for l in DATASET.read_text().splitlines() if l.strip()]
    url_domain = {d["url"]: d["notes"] for d in ds}
    my_urls = set(url_domain)

    rows = fetch_rows(150)
    # keep only our 5 models x 20 urls, dedupe to the newest per (model,url)
    seen: set[tuple[str, str]] = set()
    runs: list[dict] = []
    for r in rows:
        key = (r["model"], r["url"])
        if r["model"] in MODELS and r["url"] in my_urls and key not in seen:
            seen.add(key)
            runs.append(r)
    runs = [r for r in runs if r["model"] in MODELS]

    # ---- per-model aggregates ----
    agg: dict[str, dict] = {m: {"n": 0, "ok": 0, "iters": 0, "rt": 0.0, "cost": 0.0} for m in MODELS}
    for r in runs:
        a = agg[r["model"]]
        a["n"] += 1
        a["ok"] += int(r["success"])
        a["iters"] += r["iterations"]
        a["rt"] += r["runtime_seconds"]
        a["cost"] += r["cost_usd"]

    # ---- per-domain x model matrix ----
    matrix: dict[str, dict[str, str]] = defaultdict(dict)
    for r in runs:
        matrix[url_domain.get(r["url"], urlparse(r["url"]).netloc)][r["model"]] = (
            "OK" if r["success"] else "fail"
        )

    # ---- write CSV + JSON ----
    (HERE / "benchmark_runs.json").write_text(json.dumps(runs, indent=2))
    with open(HERE / "benchmark_runs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["model", "domain", "url", "success", "iterations",
                    "runtime_s", "cost_usd", "downloaded_docs", "note"])
        for r in sorted(runs, key=lambda x: (x["model"], url_domain.get(x["url"], ""))):
            w.writerow([r["model"], url_domain.get(r["url"], ""), r["url"], r["success"],
                        r["iterations"], round(r["runtime_seconds"], 2),
                        round(r["cost_usd"], 6), r["downloaded_docs"], r["note"][:200]])

    # ---- markdown ----
    L: list[str] = []
    total = len(runs)
    L.append("# LLM Benchmark — 20 Domains × 5 Low-Cost LLMs\n")
    L.append(f"*Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · "
             f"source: `data/publications_21_06_2026.xlsx` · {total} runs (20 domains × {len(MODELS)} models)*\n")
    L.append("## Method\n")
    L.append("Each URL was passed to the production **LLM scraper-generation feedback loop** "
             "(`phase1_llm_scraper.feedback_loop.run_feedback_loop`, `max_iterations=2`): the model reads "
             "the portal HTML, writes Playwright code, the sandbox runs it against the **live** portal, and "
             "the model self-heals from the error once. A run counts as **success** only if real "
             "documents were downloaded (recall ≥ 0.5). Run **inside the Docker worker container** "
             "(which has Chromium) by `data/benchmarks/run_in_container.py`; each result is written as an "
             "`evaluation_runs` row, so the results also appear on the frontend **/evaluation** page. "
             "No cascade fallbacks (deterministic/CUA/manual) were used — this isolates pure LLM capability.\n")
    L.append("> **Why not the `/api/evaluation/run` endpoint?** The batch endpoint holds one DB session open "
             "across all 100 runs; the first auth-gated portal (`barmer.de`) ran 361 s and tripped Postgres' "
             "300 s `idle-in-transaction` limit, killing the task at run #5. The in-container runner fixes this "
             "with a per-run hard timeout, a fresh short-lived DB session per insert, bounded iterations, and "
             "concurrency 3 (gentle on OpenRouter).\n")
    L.append("> **Limitation:** the 140 s per-run timeout is enforced on the awaiting coroutine, but blocking work "
             "inside threaded sandbox/LLM-retry paths can overrun it — a few `llama-4-maverick` runs reached "
             "1000–1640 s due to OpenRouter `incomplete chunked read` retries. This inflates that model's avg "
             "runtime but did not stall the overall run.\n")

    # leaderboard
    L.append("## Model Leaderboard\n")
    L.append("| Rank | Model | List $/1M (in/out) | Success | Rate | Avg iters | Avg runtime | Total cost | $/URL |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    order = sorted(MODELS, key=lambda m: (-(agg[m]["ok"] / agg[m]["n"] if agg[m]["n"] else 0),
                                          agg[m]["cost"]))
    for i, m in enumerate(order, 1):
        a = agg[m]
        n = a["n"] or 1
        pi, po = PRICE[m]
        L.append(f"| {i} | `{short(m)}` | {pi}/{po} | {a['ok']}/{a['n']} | "
                 f"**{100*a['ok']/n:.0f}%** | {a['iters']/n:.2f} | {a['rt']/n:.1f}s | "
                 f"${a['cost']:.4f} | ${a['cost']/n:.6f} |")
    L.append("")

    # totals
    tot_cost = sum(a["cost"] for a in agg.values())
    tot_ok = sum(a["ok"] for a in agg.values())
    L.append(f"**Totals:** {tot_ok}/{total} successful runs across all models · "
             f"combined spend **${tot_cost:.4f}**.\n")

    # matrix
    L.append("## Per-Domain Success Matrix\n")
    hdr = "| # | Domain | " + " | ".join(short(m) for m in MODELS) + " | wins |"
    L.append(hdr)
    L.append("|---|" + "---|" * (len(MODELS) + 2))
    for i, d in enumerate(ds, 1):
        dom = d["notes"]
        cells = []
        wins = 0
        for m in MODELS:
            v = matrix.get(dom, {}).get(m, "—")
            if v == "OK":
                wins += 1
                cells.append("✅")
            elif v == "fail":
                cells.append("❌")
            else:
                cells.append("—")
        L.append(f"| {i} | `{dom}` | " + " | ".join(cells) + f" | {wins}/5 |")
    L.append("")
    # per-domain solvable count
    solvable = sum(1 for d in ds if any(matrix.get(d["notes"], {}).get(m) == "OK" for m in MODELS))
    L.append(f"**{solvable}/20 domains** were solved by at least one model; "
             f"**{20-solvable}/20** were unsolved by every model (typically auth-gated / login-walled portals).\n")

    # failure reasons
    L.append("## Common Failure Reasons\n")
    reasons: dict[str, int] = defaultdict(int)
    for r in runs:
        if not r["success"] and r["note"]:
            key = r["note"].split(":")[0].strip()[:60] or "unknown"
            reasons[key] += 1
    L.append("| Failure reason (note prefix) | Count |")
    L.append("|---|---|")
    for k, v in sorted(reasons.items(), key=lambda x: -x[1])[:12]:
        L.append(f"| {k} | {v} |")
    L.append("")
    L.append("---\n")
    L.append("*Artifacts: [`benchmark_runs.csv`](benchmark_runs.csv) · "
             "[`benchmark_runs.json`](benchmark_runs.json) · dataset [`bench_20_domains.jsonl`](bench_20_domains.jsonl)*")

    (HERE / "benchmark_report.md").write_text("\n".join(L))
    print(f"OK — {total} runs documented.")
    print("  data/benchmarks/benchmark_report.md")
    print("  data/benchmarks/benchmark_runs.csv")
    print("  data/benchmarks/benchmark_runs.json")


if __name__ == "__main__":
    main()
