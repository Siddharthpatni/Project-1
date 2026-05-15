#!/usr/bin/env python3
"""
Build a production-grade, exhaustive REPORT.md from full_results.json.
Reads:    runs/<ts>/full_results.json
Writes:   runs/<ts>/REPORT.md  (overwriting the original)
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── Helpers ────────────────────────────────────────────────────────

def medal(rank: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}.")


def status_icon(s: str) -> str:
    return {
        "SUCCESS": "✅",
        "PARTIAL": "⚠️",
        "FAILED":  "❌",
        "ERROR":   "💥",
        "SKIPPED": "⏭️",
    }.get(s, "❓")


def bar(value: float, max_value: float, width: int = 20, char: str = "█") -> str:
    if max_value <= 0:
        return " " * width
    filled = int((value / max_value) * width)
    filled = max(0, min(width, filled))
    return char * filled + "·" * (width - filled)


def short(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def fmt_money(x: float) -> str:
    if x == 0:
        return "$0.0000"
    if x < 0.001:
        return f"${x:.6f}"
    return f"${x:.4f}"


def fmt_int(n: int | float) -> str:
    return f"{n:,}"


# ── Aggregations ───────────────────────────────────────────────────

def aggregate_by_model(experiments: list[dict]) -> dict[str, dict]:
    by = defaultdict(list)
    for e in experiments:
        by[e["model"]].append(e)

    out = {}
    for model, exps in by.items():
        succ    = sum(1 for e in exps if e["status"] == "SUCCESS")
        partial = sum(1 for e in exps if e["status"] == "PARTIAL")
        failed  = sum(1 for e in exps if e["status"] == "FAILED")
        errored = sum(1 for e in exps if e["status"] == "ERROR")
        skipped = sum(1 for e in exps if e["status"] == "SKIPPED")
        active  = max(1, len(exps) - skipped)

        total_attempts = sum(e["attempts"] for e in exps)
        val_passes     = sum(1 for e in exps if e["final_validator_ok"])
        feedback_used  = sum(1 for e in exps if e["attempts"] > 1)
        feedback_ok    = sum(1 for e in exps if e["attempts"] > 1 and e["status"] == "SUCCESS")

        out[model] = {
            "provider":      exps[0].get("provider", "?"),
            "model_id":      exps[0].get("model_id", "?"),
            "n":             len(exps),
            "active":        active,
            "success":       succ,
            "partial":       partial,
            "failed":        failed,
            "errored":       errored,
            "skipped":       skipped,
            "success_rate":  succ / active * 100,
            "validator_rate": val_passes / max(1, len(exps)) * 100,
            "feedback_used":  feedback_used,
            "feedback_ok":    feedback_ok,
            "feedback_recovery_rate": feedback_ok / max(1, feedback_used) * 100 if feedback_used else 0.0,
            "avg_recall":    sum(e["recall_pct"] for e in exps) / active,
            "docs_unique":   sum(e["docs_unique"] for e in exps),
            "docs_downloaded": sum(e["docs_downloaded"] for e in exps),
            "dup_count":     sum(e["duplicate_count"] for e in exps),
            "avg_e2e_s":     sum(e["end_to_end_s"] for e in exps) / active,
            "avg_gen_s":     sum(e["total_generation_s"] for e in exps) / active,
            "avg_exec_s":    sum(e["total_execution_s"]  for e in exps) / active,
            "median_e2e_s":  sorted(e["end_to_end_s"] for e in exps)[len(exps)//2],
            "min_e2e_s":     min(e["end_to_end_s"] for e in exps),
            "max_e2e_s":     max(e["end_to_end_s"] for e in exps),
            "avg_attempts":  total_attempts / active,
            "total_cost":    sum(e["cost_usd"] for e in exps),
            "tokens_in":     sum(e["tokens_in"]  for e in exps),
            "tokens_out":    sum(e["tokens_out"] for e in exps),
            "total_tokens":  sum(e["tokens_in"] + e["tokens_out"] for e in exps),
            "cost_per_succ": sum(e["cost_usd"] for e in exps) / max(1, succ),
            "cost_per_doc":  sum(e["cost_usd"] for e in exps) / max(1, sum(e["docs_unique"] for e in exps)),
            "experiments":   exps,
        }
    return out


def aggregate_by_url(experiments: list[dict]) -> dict[str, dict]:
    by = defaultdict(list)
    for e in experiments:
        by[e["url"]].append(e)

    out = {}
    for url, exps in by.items():
        succ      = sum(1 for e in exps if e["status"] == "SUCCESS")
        ceiling   = max((e["docs_unique"] for e in exps), default=0)
        best      = max(exps, key=lambda x: (x["docs_unique"], x["recall_pct"], -x["end_to_end_s"]))
        out[url] = {
            "id":          exps[0]["url_id"],
            "domain":      exps[0].get("domain", urlparse(url).netloc),
            "n":           len(exps),
            "success":     succ,
            "ceiling":     ceiling,
            "avg_recall":  sum(e["recall_pct"] for e in exps) / max(1, len(exps)),
            "avg_e2e_s":   sum(e["end_to_end_s"] for e in exps) / max(1, len(exps)),
            "total_cost":  sum(e["cost_usd"] for e in exps),
            "best_model":  best["model"] if ceiling > 0 else "—",
            "experiments": exps,
        }
    return out


# ── Section builders ───────────────────────────────────────────────

def section_header(run_dir: Path, totals: dict, models: int, urls: int, total_exp: int) -> list[str]:
    now = datetime.now(timezone.utc)
    return [
        "# Vergabepilot Phase-1 · Multi-LLM Scraper Benchmark",
        "",
        f"> **Run:** `{run_dir.name}`  ·  "
        f"**Generated:** `{now.strftime('%Y-%m-%d %H:%M UTC')}`  ·  "
        f"**Scope:** {models} models × {urls} URLs · {total_exp} experiments",
        "",
        f"> **Wall time:** {totals['wall_h']:.2f}h  ·  "
        f"**Total cost:** {fmt_money(totals['cost'])}  ·  "
        f"**Total tokens:** {fmt_int(totals['tokens'])}  ·  "
        f"**Unique documents:** {totals['docs_unique']}",
        "",
        "---",
        "",
    ]


def section_tldr(per_model: dict, totals: dict, total_exp: int) -> list[str]:
    ranked = sorted(
        per_model.items(),
        key=lambda kv: (-kv[1]["success_rate"], -kv[1]["avg_recall"], kv[1]["avg_e2e_s"]),
    )
    winner       = ranked[0] if ranked else None
    cheapest     = min(((k, v) for k, v in per_model.items() if v["success"] > 0),
                      key=lambda kv: kv[1]["cost_per_succ"], default=None)
    fastest      = min(per_model.items(), key=lambda kv: kv[1]["avg_e2e_s"]) if per_model else None
    best_recall  = max(per_model.items(), key=lambda kv: kv[1]["avg_recall"]) if per_model else None

    lines = [
        "## 1 · TL;DR — Executive Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **Total experiments** | {total_exp} |",
        f"| **Successful** | {totals['success']}/{total_exp} ({totals['success']/total_exp*100:.0f}%) |",
        f"| **Partial** | {totals['partial']} |",
        f"| **Failed / Errored** | {totals['failed']} / {totals['errored']} |",
        f"| **Skipped (budget cap)** | {totals['skipped']} |",
        f"| **Best model (success rate)** | `{winner[0]}` ({winner[1]['success_rate']:.0f}%) |" if winner else "| **Best model** | — |",
        f"| **Cheapest per success** | `{cheapest[0]}` ({fmt_money(cheapest[1]['cost_per_succ'])}/success) |" if cheapest else "| **Cheapest per success** | — |",
        f"| **Fastest avg E2E** | `{fastest[0]}` ({fastest[1]['avg_e2e_s']:.1f}s) |" if fastest else "| **Fastest** | — |",
        f"| **Best avg recall** | `{best_recall[0]}` ({best_recall[1]['avg_recall']:.0f}%) |" if best_recall else "| **Best recall** | — |",
        f"| **Total unique documents** | {totals['docs_unique']} |",
        f"| **Total duplicate files** | {totals['dups']} (dedup rate {totals['dup_rate']:.1f}%) |",
        f"| **Overall avg recall** | {totals['avg_recall']:.1f}% |",
        f"| **Total tokens consumed** | {fmt_int(totals['tokens'])} |",
        f"| **Total cost (USD)** | {fmt_money(totals['cost'])} |",
        f"| **Total wall time** | {totals['wall_h']:.2f}h ({totals['wall_min']:.0f} min) |",
        "",
        "**Key Findings:**",
        "",
    ]

    if winner:
        lines.append(f"- 🏆 The best model is **`{winner[0]}`** — "
                     f"{winner[1]['success']}/{winner[1]['n']} ({winner[1]['success_rate']:.0f}%) success, "
                     f"{winner[1]['avg_recall']:.0f}% avg recall, "
                     f"{fmt_money(winner[1]['total_cost'])} total cost.")
    if cheapest:
        lines.append(f"- 💰 Most cost-efficient: **`{cheapest[0]}`** at {fmt_money(cheapest[1]['cost_per_succ'])} per successful scrape "
                     f"({fmt_money(cheapest[1]['cost_per_doc'])} per unique document).")
    if fastest:
        lines.append(f"- ⚡ Fastest end-to-end: **`{fastest[0]}`** averaging {fastest[1]['avg_e2e_s']:.1f}s "
                     f"(min {fastest[1]['min_e2e_s']:.1f}s, max {fastest[1]['max_e2e_s']:.1f}s).")
    if totals['dups'] > 0:
        lines.append(f"- 🔁 SHA256 deduplication caught **{totals['dups']} duplicate file(s)** across all experiments.")
    if totals['failed'] + totals['errored'] > 0:
        lines.append(f"- ⚠️  **{totals['failed'] + totals['errored']}** experiments ended in FAILED/ERROR — see §11 for root-cause breakdown.")

    feedback_total = sum(v["feedback_used"] for v in per_model.values())
    feedback_recov = sum(v["feedback_ok"]   for v in per_model.values())
    if feedback_total > 0:
        lines.append(f"- 🔄 Feedback loop triggered for **{feedback_total}/{total_exp}** experiments; "
                     f"**{feedback_recov}** ({feedback_recov/feedback_total*100:.0f}%) recovered to SUCCESS.")

    lines += ["", "---", ""]
    return lines


def section_leaderboard(per_model: dict) -> list[str]:
    ranked = sorted(
        per_model.items(),
        key=lambda kv: (-kv[1]["success_rate"], -kv[1]["avg_recall"], kv[1]["avg_e2e_s"]),
    )

    lines = [
        "## 2 · Model Leaderboard",
        "",
        "Ranked by: success rate (desc) → avg recall (desc) → avg E2E time (asc).",
        "",
        "| Rank | Model | Provider | Success | Partial | Fail | Error | Succ% | Recall | Avg E2E | Avg Att | Docs | Dups | Cost | Tokens |",
        "|------|-------|----------|---------|---------|------|-------|-------|--------|---------|---------|------|------|------|--------|",
    ]
    for i, (name, s) in enumerate(ranked, 1):
        lines.append(
            f"| {medal(i)} | **`{name}`** | {s['provider']} "
            f"| {s['success']}/{s['n']} | {s['partial']} | {s['failed']} | {s['errored']} "
            f"| {s['success_rate']:.0f}% | {s['avg_recall']:.0f}% "
            f"| {s['avg_e2e_s']:.1f}s | {s['avg_attempts']:.1f} "
            f"| {s['docs_unique']} | {s['dup_count']} "
            f"| {fmt_money(s['total_cost'])} | {fmt_int(s['total_tokens'])} |"
        )

    lines += ["", "---", ""]
    return lines


def section_visual_bars(per_model: dict) -> list[str]:
    if not per_model:
        return []

    ranked = sorted(per_model.items(), key=lambda kv: -kv[1]["success_rate"])
    max_succ = max(v["success_rate"] for v in per_model.values())
    max_cost = max(v["total_cost"]   for v in per_model.values()) or 1.0
    max_e2e  = max(v["avg_e2e_s"]    for v in per_model.values()) or 1.0
    max_doc  = max(v["docs_unique"]  for v in per_model.values()) or 1.0

    lines = [
        "## 3 · Visual Comparison (ASCII Bar Charts)",
        "",
        "### 3.1 Success Rate (% of experiments succeeded)",
        "",
        "```",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: -kv[1]["success_rate"]):
        lines.append(f"  {name:<24} |{bar(s['success_rate'], 100, 30)}| {s['success_rate']:>5.0f}%")
    lines += ["```", ""]

    lines += [
        "### 3.2 Avg Recall (consensus-ceiling-based)",
        "",
        "```",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: -kv[1]["avg_recall"]):
        lines.append(f"  {name:<24} |{bar(s['avg_recall'], 100, 30)}| {s['avg_recall']:>5.0f}%")
    lines += ["```", ""]

    lines += [
        "### 3.3 Avg End-to-End Time (lower is better)",
        "",
        "```",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: kv[1]["avg_e2e_s"]):
        lines.append(f"  {name:<24} |{bar(s['avg_e2e_s'], max_e2e, 30)}| {s['avg_e2e_s']:>7.1f}s")
    lines += ["```", ""]

    lines += [
        "### 3.4 Total Cost (USD)",
        "",
        "```",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: kv[1]["total_cost"]):
        lines.append(f"  {name:<24} |{bar(s['total_cost'], max_cost, 30)}| {fmt_money(s['total_cost'])}")
    lines += ["```", ""]

    lines += [
        "### 3.5 Unique Documents Downloaded",
        "",
        "```",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: -kv[1]["docs_unique"]):
        lines.append(f"  {name:<24} |{bar(s['docs_unique'], max_doc, 30)}| {s['docs_unique']:>4} docs")
    lines += ["```", "", "---", ""]
    return lines


def section_cost_efficiency(per_model: dict) -> list[str]:
    lines = [
        "## 4 · Cost-Efficiency Analysis",
        "",
        "All costs sourced directly from OpenRouter's billed `usage.cost` field — not estimates.",
        "",
        "| Model | Total Cost | Cost / Success | Cost / Unique Doc | Input Tokens | Output Tokens | Total Tokens | $/1M Tokens |",
        "|-------|-----------|----------------|-------------------|--------------|---------------|--------------|-------------|",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: kv[1]["total_cost"]):
        per_m = (s["total_cost"] / s["total_tokens"] * 1_000_000) if s["total_tokens"] > 0 else 0
        lines.append(
            f"| `{name}` | {fmt_money(s['total_cost'])} "
            f"| {fmt_money(s['cost_per_succ'])} | {fmt_money(s['cost_per_doc'])} "
            f"| {fmt_int(s['tokens_in'])} | {fmt_int(s['tokens_out'])} | {fmt_int(s['total_tokens'])} "
            f"| {fmt_money(per_m)} |"
        )
    lines += ["", "---", ""]
    return lines


def section_speed(per_model: dict) -> list[str]:
    lines = [
        "## 5 · Speed & Latency Analysis",
        "",
        "| Model | Avg E2E | Median E2E | Min E2E | Max E2E | Avg Generation | Avg Execution | Avg Attempts |",
        "|-------|---------|------------|---------|---------|----------------|---------------|--------------|",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: kv[1]["avg_e2e_s"]):
        lines.append(
            f"| `{name}` | {s['avg_e2e_s']:.1f}s | {s['median_e2e_s']:.1f}s "
            f"| {s['min_e2e_s']:.1f}s | {s['max_e2e_s']:.1f}s "
            f"| {s['avg_gen_s']:.1f}s | {s['avg_exec_s']:.1f}s "
            f"| {s['avg_attempts']:.1f} |"
        )
    lines += ["", "---", ""]
    return lines


def section_per_model_cards(per_model: dict, per_url: dict) -> list[str]:
    lines = [
        "## 6 · Per-Model Detailed Cards",
        "",
        "Comprehensive breakdown for **every** model — not just the leaders.",
        "",
    ]

    ranked = sorted(per_model.items(),
                    key=lambda kv: (-kv[1]["success_rate"], -kv[1]["avg_recall"], kv[1]["avg_e2e_s"]))

    for i, (name, s) in enumerate(ranked, 1):
        lines += [
            f"### 6.{i} `{name}`  {medal(i)}",
            "",
            f"- **Provider:** `{s['provider']}`",
            f"- **OpenRouter model ID:** `{s['model_id']}`",
            f"- **Experiments:** {s['n']} (active {s['active']}, skipped {s['skipped']})",
            "",
            "**Outcome distribution:**",
            "",
            f"| ✅ Success | ⚠️ Partial | ❌ Failed | 💥 Errored | ⏭️ Skipped |",
            "|---|---|---|---|---|",
            f"| {s['success']} | {s['partial']} | {s['failed']} | {s['errored']} | {s['skipped']} |",
            "",
            "**Performance metrics:**",
            "",
            f"| Metric | Value |",
            "|--------|-------|",
            f"| Success rate | **{s['success_rate']:.0f}%** |",
            f"| Avg recall | {s['avg_recall']:.1f}% |",
            f"| Validator pass rate | {s['validator_rate']:.0f}% |",
            f"| Unique documents | {s['docs_unique']} |",
            f"| Total documents (pre-dedup) | {s['docs_downloaded']} |",
            f"| Duplicate files | {s['dup_count']} |",
            f"| Avg E2E time | {s['avg_e2e_s']:.1f}s (median {s['median_e2e_s']:.1f}s) |",
            f"| E2E range | {s['min_e2e_s']:.1f}s — {s['max_e2e_s']:.1f}s |",
            f"| Avg generation time | {s['avg_gen_s']:.1f}s |",
            f"| Avg execution time | {s['avg_exec_s']:.1f}s |",
            f"| Avg attempts | {s['avg_attempts']:.1f} |",
            f"| Feedback loop usage | {s['feedback_used']}/{s['n']} ({s['feedback_used']/max(1,s['n'])*100:.0f}%) |",
            f"| Feedback recovery rate | {s['feedback_recovery_rate']:.0f}% ({s['feedback_ok']}/{max(1,s['feedback_used'])}) |",
            f"| Total cost | {fmt_money(s['total_cost'])} |",
            f"| Cost per success | {fmt_money(s['cost_per_succ'])} |",
            f"| Cost per unique doc | {fmt_money(s['cost_per_doc'])} |",
            f"| Total tokens | {fmt_int(s['total_tokens'])} (in {fmt_int(s['tokens_in'])} / out {fmt_int(s['tokens_out'])}) |",
            "",
            "**Per-URL outcomes:**",
            "",
            "| Domain | Status | Att. | Docs | Recall | E2E | Cost | Tokens |",
            "|--------|--------|------|------|--------|-----|------|--------|",
        ]

        for exp in sorted(s["experiments"], key=lambda x: x["url_id"]):
            domain = exp.get("domain") or urlparse(exp["url"]).netloc
            lines.append(
                f"| `{short(domain, 32)}` | {status_icon(exp['status'])} {exp['status']} "
                f"| {exp['attempts']} | {exp['docs_unique']} "
                f"| {exp['recall_pct']:.0f}% | {exp['end_to_end_s']:.1f}s "
                f"| {fmt_money(exp['cost_usd'])} | {fmt_int(exp['tokens_in']+exp['tokens_out'])} |"
            )
        lines += ["", "---", ""]
    return lines


def section_per_url_cards(per_url: dict) -> list[str]:
    lines = [
        "## 7 · Per-URL Detailed Cards",
        "",
        "Every URL × every model — full visibility into which models handled which sites.",
        "",
    ]

    for i, (url, u) in enumerate(per_url.items(), 1):
        succ_pct = u['success'] / max(1, u['n']) * 100
        lines += [
            f"### 7.{i} `{u['domain']}`",
            "",
            f"- **URL:** `{url}`",
            f"- **URL ID:** `{u['id']}`",
            f"- **Models tested:** {u['n']}  ·  **Success:** {u['success']}/{u['n']} ({succ_pct:.0f}%)",
            f"- **Document ceiling:** {u['ceiling']} unique  ·  **Avg recall:** {u['avg_recall']:.0f}%",
            f"- **Avg E2E time:** {u['avg_e2e_s']:.1f}s  ·  **Total cost across models:** {fmt_money(u['total_cost'])}",
            f"- **Best model on this URL:** `{u['best_model']}`",
            "",
            "| Model | Status | Att. | Docs Found | Recall | E2E (s) | Gen (s) | Exec (s) | Cost | Tokens |",
            "|-------|--------|------|------------|--------|---------|---------|----------|------|--------|",
        ]
        for exp in sorted(u["experiments"], key=lambda x: (-x["docs_unique"], x["model"])):
            lines.append(
                f"| `{exp['model']}` | {status_icon(exp['status'])} {exp['status']} "
                f"| {exp['attempts']} | {exp['docs_unique']} | {exp['recall_pct']:.0f}% "
                f"| {exp['end_to_end_s']:.1f} | {exp['total_generation_s']:.1f} | {exp['total_execution_s']:.1f} "
                f"| {fmt_money(exp['cost_usd'])} | {fmt_int(exp['tokens_in']+exp['tokens_out'])} |"
            )
        lines += ["", "---", ""]
    return lines


def section_per_attempt(experiments: list[dict]) -> list[str]:
    lines = [
        "## 8 · Per-Attempt Trace (every single LLM call)",
        "",
        "Each row is one attempt at scraping one URL with one model. "
        "Multiple rows per cell when the feedback loop retried.",
        "",
        "| Model | URL ID | Att. | Val OK | Exec OK | Docs | Gen (s) | Exec (s) | Tokens In | Tokens Out | Cost | Error (truncated) |",
        "|-------|--------|------|--------|---------|------|---------|----------|-----------|------------|------|-------------------|",
    ]
    for exp in sorted(experiments, key=lambda x: (x["url_id"], x["model"])):
        for rec in exp.get("attempt_records", []):
            err = (rec.get("error") or "")[:60].replace("|", "\\|")
            lines.append(
                f"| `{exp['model']}` | `{exp['url_id'][:8]}` | {rec['attempt']} "
                f"| {'✓' if rec['validator_ok'] else '✗'} "
                f"| {'✓' if rec['exec_ok'] else '✗'} "
                f"| {rec['docs_downloaded']} "
                f"| {rec['generation_s']:.1f} | {rec['execution_s']:.1f} "
                f"| {fmt_int(rec['tokens_in'])} | {fmt_int(rec['tokens_out'])} "
                f"| {fmt_money(rec['cost_usd'])} "
                f"| `{err}` |"
            )
    lines += ["", "---", ""]
    return lines


def section_reliability_matrix(per_model: dict, per_url: dict) -> list[str]:
    """Heatmap-style table: rows=models, cols=URLs, cells=outcome icon + docs."""
    models = sorted(per_model.keys(),
                    key=lambda m: (-per_model[m]["success_rate"], -per_model[m]["avg_recall"]))
    urls = list(per_url.keys())

    lines = [
        "## 9 · Reliability Matrix (Model × URL)",
        "",
        "Compact at-a-glance view. Each cell shows status + unique-doc count.",
        "",
    ]

    # Header
    header = "| Model | " + " | ".join(f"{per_url[u]['domain'][:18]}" for u in urls) + " |"
    sep    = "|-------|" + "|".join(["-------"] * len(urls)) + "|"
    lines += [header, sep]

    # Rows
    for m in models:
        row_cells = []
        for u in urls:
            exp = next((e for e in per_url[u]["experiments"] if e["model"] == m), None)
            if not exp:
                row_cells.append("  —  ")
            else:
                row_cells.append(f"{status_icon(exp['status'])} {exp['docs_unique']}d/{exp['recall_pct']:.0f}%")
        lines.append(f"| `{m}` | " + " | ".join(row_cells) + " |")

    lines += ["", "Legend: ✅ SUCCESS  ⚠️ PARTIAL  ❌ FAILED  💥 ERROR  ⏭️ SKIPPED", "", "---", ""]
    return lines


def section_token_economy(per_model: dict) -> list[str]:
    lines = [
        "## 10 · Token Economy Analysis",
        "",
        "How chatty each model is, and what that costs.",
        "",
        "| Model | Avg In/exp | Avg Out/exp | Out:In Ratio | $/M Input | $/M Output | $/M Total |",
        "|-------|------------|-------------|--------------|-----------|------------|-----------|",
    ]
    for name, s in sorted(per_model.items(), key=lambda kv: -kv[1]["total_tokens"]):
        avg_in  = s["tokens_in"]  / max(1, s["active"])
        avg_out = s["tokens_out"] / max(1, s["active"])
        ratio   = avg_out / max(1, avg_in)
        per_m_total = s["total_cost"] / max(1, s["total_tokens"]) * 1_000_000
        per_m_in    = per_m_total * (s["tokens_in"] / max(1, s["total_tokens"]))
        per_m_out   = per_m_total * (s["tokens_out"] / max(1, s["total_tokens"]))
        lines.append(
            f"| `{name}` | {fmt_int(int(avg_in))} | {fmt_int(int(avg_out))} | {ratio:.2f}× "
            f"| {fmt_money(per_m_in)} | {fmt_money(per_m_out)} | {fmt_money(per_m_total)} |"
        )
    lines += ["", "---", ""]
    return lines


def section_failure_analysis(experiments: list[dict], per_model: dict) -> list[str]:
    failures = [e for e in experiments if e["status"] in ("FAILED", "ERROR")]
    lines = [
        "## 11 · Failure Analysis",
        "",
    ]
    if not failures:
        lines.append("🎉 No failures recorded in this run.")
        lines += ["", "---", ""]
        return lines

    lines.append(f"**{len(failures)} / {len(experiments)}** experiments ended in FAILED or ERROR.")
    lines.append("")

    # Per-model breakdown
    lines += [
        "### 11.1 Failure count by model",
        "",
        "| Model | FAILED | ERROR | Total fails | Fail % |",
        "|-------|--------|-------|-------------|--------|",
    ]
    for m, s in sorted(per_model.items(), key=lambda kv: -(kv[1]["failed"] + kv[1]["errored"])):
        if s["failed"] + s["errored"] == 0:
            continue
        fail_pct = (s["failed"] + s["errored"]) / s["n"] * 100
        lines.append(f"| `{m}` | {s['failed']} | {s['errored']} | {s['failed']+s['errored']} | {fail_pct:.0f}% |")
    lines += [""]

    # Root causes
    lines += [
        "### 11.2 Root cause distribution",
        "",
        "| Count | Error pattern |",
        "|-------|---------------|",
    ]
    by_reason = defaultdict(int)
    for f in failures:
        key = (f.get("error") or "Unknown — 0 docs downloaded")[:120]
        by_reason[key] += 1
    for reason, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        safe = reason.replace("|", "\\|")
        lines.append(f"| {n}× | `{safe}` |")
    lines += [""]

    # Validator vs Exec status
    lines += [
        "### 11.3 Validator pass / Exec success in failed experiments",
        "",
        "Tells us whether the LLM is producing **unsafe code** (val ✗) or "
        "**code that runs but fails** (val ✓ / exec ✗).",
        "",
        "| Model | URL | Val | Exec | Att. | First-attempt error |",
        "|-------|-----|-----|------|------|---------------------|",
    ]
    for f in failures:
        domain = f.get("domain") or urlparse(f["url"]).netloc
        first_err = ""
        if f.get("attempt_records"):
            first_err = (f["attempt_records"][0].get("error") or "")[:80].replace("|", "\\|")
        lines.append(
            f"| `{f['model']}` | `{short(domain, 35)}` "
            f"| {'✓' if f['final_validator_ok'] else '✗'} "
            f"| {'✓' if f['final_exec_ok'] else '✗'} "
            f"| {f['attempts']} | `{first_err}` |"
        )

    lines += ["", "---", ""]
    return lines


def section_recommendations(per_model: dict, totals: dict, total_exp: int) -> list[str]:
    ranked = sorted(per_model.items(),
                    key=lambda kv: (-kv[1]["success_rate"], -kv[1]["avg_recall"], kv[1]["avg_e2e_s"]))

    cheapest = min(((k, v) for k, v in per_model.items() if v["success"] > 0),
                   key=lambda kv: kv[1]["cost_per_succ"], default=None)
    fastest  = min(per_model.items(), key=lambda kv: kv[1]["avg_e2e_s"]) if per_model else None
    bestrec  = max(per_model.items(), key=lambda kv: kv[1]["avg_recall"]) if per_model else None

    lines = [
        "## 12 · Recommendations & Insights",
        "",
        "### 12.1 Use-case → Model recommendation matrix",
        "",
        "| Use case | Recommended model | Why |",
        "|----------|-------------------|-----|",
    ]
    if ranked:
        b = ranked[0]
        lines.append(f"| **Production reliability** | `{b[0]}` | "
                     f"highest success rate ({b[1]['success_rate']:.0f}%), "
                     f"recall {b[1]['avg_recall']:.0f}% |")
    if cheapest:
        c = cheapest
        lines.append(f"| **Budget / volume scraping** | `{c[0]}` | "
                     f"cheapest per success ({fmt_money(c[1]['cost_per_succ'])}), "
                     f"still {c[1]['success_rate']:.0f}% reliable |")
    if fastest:
        f = fastest
        lines.append(f"| **Latency-sensitive (interactive)** | `{f[0]}` | "
                     f"fastest avg E2E ({f[1]['avg_e2e_s']:.1f}s), "
                     f"{f[1]['success_rate']:.0f}% success |")
    if bestrec:
        r = bestrec
        lines.append(f"| **Maximum document recall** | `{r[0]}` | "
                     f"highest avg recall ({r[1]['avg_recall']:.0f}%), "
                     f"captures {r[1]['docs_unique']} unique docs |")

    lines += ["", "### 12.2 Models to avoid for this task type", ""]
    avoid = [(m, s) for m, s in per_model.items() if s["success_rate"] < 25]
    if avoid:
        for m, s in sorted(avoid, key=lambda kv: kv[1]["success_rate"]):
            lines.append(f"- ❌ **`{m}`** — {s['success_rate']:.0f}% success "
                         f"({s['failed']+s['errored']}/{s['n']} fails). "
                         f"Validator pass rate {s['validator_rate']:.0f}%.")
    else:
        lines.append("- All tested models achieved at least 25% success rate.")

    lines += ["", "### 12.3 Operational insights", ""]
    feedback_total = sum(v["feedback_used"] for v in per_model.values())
    feedback_recov = sum(v["feedback_ok"]   for v in per_model.values())
    if feedback_total > 0:
        rate = feedback_recov / feedback_total * 100
        lines.append(f"- **Feedback loop ROI:** {feedback_recov}/{feedback_total} ({rate:.0f}%) of retried experiments recovered. "
                     f"Worth keeping for production runs.")
    if totals['dups'] > 0:
        lines.append(f"- **Deduplication value:** {totals['dups']} duplicate file(s) were correctly identified by SHA256 hashing. "
                     f"Without dedup, total counts would be inflated by {totals['dup_rate']:.1f}%.")
    expensive = max(per_model.items(), key=lambda kv: kv[1]["total_cost"])
    if expensive:
        ratio = expensive[1]["total_cost"] / max(0.0001, min(v["total_cost"] for v in per_model.values()))
        lines.append(f"- **Cost spread:** the most expensive model (`{expensive[0]}`) costs {ratio:.0f}× more per run "
                     f"than the cheapest. Cost-success-recall trade-off is real.")

    lines += ["", "---", ""]
    return lines


def section_reproducibility(run_dir: Path, models: int, urls: int) -> list[str]:
    return [
        "## 13 · Reproducibility",
        "",
        "Anyone with the same OpenRouter API key can re-run this exact benchmark:",
        "",
        "```bash",
        f"cd {run_dir.parent.parent}",
        f"python multi_llm_evaluator.py --resume {run_dir} --max-budget 5.00",
        "```",
        "",
        "**Artifacts written by this run:**",
        "",
        f"- `{run_dir.name}/REPORT.md` — this report",
        f"- `{run_dir.name}/full_results.json` — raw per-experiment data, all attempt records, all token counts",
        f"- `{run_dir.name}/detailed_results.csv` — flat table for spreadsheet analysis",
        f"- `{run_dir.name}/<model>/<url-id>/code/attempt_N.py` — every generated scraper",
        f"- `{run_dir.name}/<model>/<url-id>/downloads/` — every downloaded document",
        "",
        f"**Test scope:** {models} models × {urls} URLs = {models * urls} experiments. ",
        "Per-provider concurrency caps prevent rate-limit errors. Token costs are sourced from "
        "OpenRouter's `usage.cost` field — billed amounts, not estimates.",
        "",
        "---",
        "",
    ]


# ── Main ───────────────────────────────────────────────────────────

def build_report(run_dir: Path) -> None:
    json_path = run_dir / "full_results.json"
    if not json_path.is_file():
        print(f"ERROR: {json_path} not found", file=sys.stderr)
        sys.exit(1)

    with open(json_path, encoding="utf-8") as f:
        raw = json.load(f)

    experiments = raw["experiments"]
    if not experiments:
        print("ERROR: no experiments in JSON", file=sys.stderr)
        sys.exit(1)

    per_model = aggregate_by_model(experiments)
    per_url   = aggregate_by_url(experiments)

    # Totals
    succ = sum(1 for e in experiments if e["status"] == "SUCCESS")
    part = sum(1 for e in experiments if e["status"] == "PARTIAL")
    fail = sum(1 for e in experiments if e["status"] == "FAILED")
    err  = sum(1 for e in experiments if e["status"] == "ERROR")
    skip = sum(1 for e in experiments if e["status"] == "SKIPPED")
    total_dl  = sum(e["docs_downloaded"] for e in experiments)
    total_uq  = sum(e["docs_unique"]     for e in experiments)
    total_dup = sum(e["duplicate_count"] for e in experiments)
    wall_s    = sum(e["end_to_end_s"]    for e in experiments)

    totals = {
        "success":       succ,
        "partial":       part,
        "failed":        fail,
        "errored":       err,
        "skipped":       skip,
        "docs_unique":   total_uq,
        "docs_total":    total_dl,
        "dups":          total_dup,
        "dup_rate":      (total_dup / max(1, total_dl)) * 100,
        "avg_recall":    sum(e["recall_pct"] for e in experiments) / len(experiments),
        "tokens":        sum(e["tokens_in"] + e["tokens_out"] for e in experiments),
        "cost":          sum(e["cost_usd"] for e in experiments),
        "wall_s":        wall_s,
        "wall_min":      wall_s / 60,
        "wall_h":        wall_s / 3600,
    }

    # Build all sections
    lines = []
    lines += section_header(run_dir, totals, len(per_model), len(per_url), len(experiments))
    lines += section_tldr(per_model, totals, len(experiments))
    lines += section_leaderboard(per_model)
    lines += section_visual_bars(per_model)
    lines += section_cost_efficiency(per_model)
    lines += section_speed(per_model)
    lines += section_per_model_cards(per_model, per_url)
    lines += section_per_url_cards(per_url)
    lines += section_per_attempt(experiments)
    lines += section_reliability_matrix(per_model, per_url)
    lines += section_token_economy(per_model)
    lines += section_failure_analysis(experiments, per_model)
    lines += section_recommendations(per_model, totals, len(experiments))
    lines += section_reproducibility(run_dir, len(per_model), len(per_url))

    lines += [
        "*Report generated by Vergabepilot Phase-1 Multi-LLM Benchmark Engine.*  ",
        f"*Run: `{run_dir.name}`  ·  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}*",
        "",
    ]

    out = run_dir / "REPORT.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"✅ REPORT.md written ({len(lines):,} lines, {out.stat().st_size / 1024:.1f} KB)")
    print(f"   {out}")


def main():
    p = argparse.ArgumentParser(description="Build production-grade REPORT.md from full_results.json")
    p.add_argument("run_dir", type=Path, help="Path to a runs/<timestamp>/ directory")
    args = p.parse_args()
    build_report(args.run_dir)


if __name__ == "__main__":
    main()
