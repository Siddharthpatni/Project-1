#!/usr/bin/env python3
"""Generate the full-cascade × 5-model comparison report (Markdown)."""
from __future__ import annotations
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RES = json.load(open(HERE / "cascade_5models_results.json"))
DS = [json.loads(l) for l in (HERE / "bench_20_domains.jsonl").read_text().splitlines() if l.strip()]
DOMAIN_ORDER = [d["notes"] for d in DS]

MODELS = [m for m in [
    "google/gemini-2.5-flash-lite", "openai/gpt-4.1-nano", "deepseek/deepseek-chat-v3-0324",
    "openai/gpt-4o-mini", "meta-llama/llama-4-maverick",
] if m in RES]

STRAT_LABEL = {
    "existing_scraper": "Existing", "deterministic_template": "Deterministic",
    "adaptive_universal": "Adaptive", "llm_generated_scraper": "LLM-generated",
    "learned_route": "Learned route", "computer_use_agent": "CUA", "manual_scraper": "Manual",
}
# Access ceiling per domain (verified against live portals; see LLM_BENCHMARK_REPORT.md)
CEIL = {
 "ausschreibung.halle.de":"public","ausschreibungen.giz.de":"public","ausschreibungen.kfw.de":"login",
 "ausschreibungen.landbw.de":"public","beschaffungen.barmer.de":"login","bieter.ehealth-evergabe.de":"login",
 "bieterportal.dfg.de":"login","bieterportal.dfg.e-va.eu":"login","bieterportal.noncd.db.de":"login",
 "bieterportal.pd-g.e-va.eu":"login","bieterportal.servicecenter-khs.e-va.eu":"login",
 "bieterzugang.deutsche-evergabe.de":"login","bi-medien.de":"login","box.fu-berlin.de":"gone",
 "bund.vergabe24.de":"public","deutsche-rentenversicherung-bund.de":"login","ec.europa.eu":"login",
 "eliagroup.sharepoint.com":"gone","eom-vp-prod.ai-hosting.de":"login","eu.eu-supply.com":"gone",
}
BADGE = {"public":"🟢","login":"🔒","gone":"⚫"}
def sh(m): return m.split("/")[-1]


def cell(res_item):
    return res_item


def main():
    # index: model -> domain -> item
    idx = {m: {it["domain"]: it for it in RES[m]["items"]} for m in MODELS}

    L=[]; P=L.append
    P("# Full Pipeline (7-Strategy Cascade) — 5-Model Comparison")
    P("")
    P(f"**Run:** the whole production cascade once per model, `force_model` pinning the LLM step.  ")
    P(f"**Dataset:** 20 domains from `data/publications_21_06_2026.xlsx`.  ")
    P(f"**Generated:** {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    P("")
    P("---")
    P("")

    # Executive summary
    rates = {m: RES[m]["success"] for m in MODELS}
    best = max(MODELS, key=lambda m: rates[m]) if MODELS else None
    P("## Executive Summary")
    P("")
    P("- The **full cascade** (EXISTING → DETERMINISTIC → ADAPTIVE → LLM_GENERATED → LEARNED_ROUTE → CUA → MANUAL) "
      "was run end-to-end for each model.")
    if best:
        P(f"- Range: **{min(rates.values())}–{max(rates.values())}/20** solved across models; best: `{sh(best)}` "
          f"({rates[best]}/20).")
    P("- Unlike the pure-LLM benchmark (3/20), the cascade reaches **7–13/20** because the free deterministic path grabs "
      "DTVP ZIPs and **CUA visually logs into** several vendor portals.")
    llm_wins = sum(1 for m in MODELS for it in RES[m]["items"]
                   if it["success"] and it["strategy"] == "llm_generated_scraper")
    P(f"- **Key caveat — the spread is mostly noise, not model quality.** The `LLM-generated` step (the only part "
      f"`force_model` changes) won **{llm_wins} domains outright across all five runs** — the free strategies and the "
      f"CUA always resolved the winnable domains first. The 7–13 range is therefore driven mainly by **CUA's "
      f"run-to-run stochasticity** (a visual agent gives slightly different results each attempt), not by which LLM "
      f"was pinned.")
    P("- **Takeaway:** for *this* pipeline, the choice among these cheap models barely moves full-system success — the "
      "deterministic + CUA + manual strategies do the heavy lifting. Model choice matters far more in the pure-LLM "
      "path (see the companion report).")
    P("")
    P("---")
    P("")

    # Leaderboard
    P("## 1. Model Leaderboard (full cascade)")
    P("")
    P("| Rank | Model (as the LLM step) | Solved | Rate | Winning strategies |")
    P("|---|---|---|---|---|")
    for i, m in enumerate(sorted(MODELS, key=lambda x:-rates[x]), 1):
        wins = Counter(it["strategy"] for it in RES[m]["items"] if it["success"])
        ws = ", ".join(f"{STRAT_LABEL.get(k,k)} {v}" for k,v in wins.most_common())
        P(f"| {i} | `{sh(m)}` | {rates[m]}/{RES[m]['total']} | **{round(100*rates[m]/RES[m]['total'])}%** | {ws or '—'} |")
    P("")
    P("---")
    P("")

    # Per-domain matrix (strategy that won, per model)
    P("## 2. Per-Domain Outcome Matrix")
    P("")
    P("Each cell shows the **winning strategy** (or ✗ if all failed).")
    P("")
    P("| Domain | Access | " + " | ".join(sh(m) for m in MODELS) + " |")
    P("|---|---|" + "---|"*len(MODELS))
    abbr = {"existing_scraper":"Exist","deterministic_template":"Determ","adaptive_universal":"Adapt",
            "llm_generated_scraper":"LLM","learned_route":"Route","computer_use_agent":"CUA","manual_scraper":"Manual"}
    for d in DOMAIN_ORDER:
        cells=[]
        for m in MODELS:
            it = idx[m].get(d, {})
            cells.append(abbr.get(it.get("strategy"), "·") if it.get("success") else "✗")
        P(f"| `{d}` | {BADGE.get(CEIL.get(d,''),'')} | " + " | ".join(cells) + " |")
    P("")
    P("Legend: 🟢 public · 🔒 vendor-login · ⚫ deleted/expired · Determ=deterministic ZIP · Exist=cached scraper · "
      "Adapt=adaptive heuristic · LLM=LLM-generated · Route=learned CUA route · CUA=visual agent · Manual=hand-written")
    P("")
    P("---")
    P("")

    # Strategy contribution
    P("## 3. Which Strategy Did the Work?")
    P("")
    P("Total wins by strategy, summed across all five model-runs:")
    P("")
    allwins = Counter()
    for m in MODELS:
        for it in RES[m]["items"]:
            if it["success"]:
                allwins[it["strategy"]] += 1
    P("| Strategy | Wins (of all model-runs) | Model-dependent? |")
    P("|---|---|---|")
    moddep = {"llm_generated_scraper":"yes"}
    for k,v in allwins.most_common():
        P(f"| {STRAT_LABEL.get(k,k)} | {v} | {moddep.get(k,'no')} |")
    P("")
    P("The free **deterministic** path and the **CUA** visual agent carry the cascade; only **LLM-generated** wins vary "
      "with the chosen model.")
    P("")
    P("---")
    P("")

    # Access-ceiling
    P("## 4. Success by Access Category")
    P("")
    P("| Access category | Domains | Avg solved across models |")
    P("|---|---|---|")
    by=defaultdict(list)
    for d in DOMAIN_ORDER: by[CEIL.get(d,'?')].append(d)
    for c,lab in [("public","🟢 Public / scrapeable"),("login","🔒 Vendor-login portal"),("gone","⚫ Deleted / expired")]:
        ds=by.get(c,[])
        if not ds: continue
        avg=sum(sum(1 for d in ds if idx[m].get(d,{}).get("success")) for m in MODELS)/len(MODELS)
        P(f"| {lab} | {len(ds)} | {avg:.1f}/{len(ds)} |")
    P("")
    P("The cascade reliably clears **public** portals and cracks a chunk of **vendor-login** ones via CUA; "
      "**deleted/expired** URLs remain unrecoverable for every model (the document is gone).")
    P("")
    P("---")
    P("")

    # Caveats
    P("## 5. Caveats")
    P("")
    P("- **Per-model isolation:** before each model's run, benchmark-generated LLM scrapers + learned routes for these "
      "20 domains were cleared and the Redis circuit-breakers/rate-limiters flushed, so one model can't win for another "
      "via a cached scraper. Hand-written `manual` scrapers are a shared baseline (model-independent).")
    P("- **CUA uses a fixed vision model** (not `force_model`) **and is stochastic** — a visual agent produces slightly "
      "different results each attempt, so its win count varies run-to-run independently of the model. This is the main "
      "source of the leaderboard spread, so treat small rank differences as noise.")
    P("- **Live-portal variance:** availability and latency vary by the minute; expired notices (HTTP 404) can differ "
      "from the pure-LLM run done on a different day.")
    P("")
    P("---")
    P("")
    P("*Companion: [`LLM_BENCHMARK_REPORT.md`](LLM_BENCHMARK_REPORT.md) (pure-LLM, no cascade). "
      "Raw data: [`cascade_5models_results.json`](cascade_5models_results.json).*")

    out = HERE / "CASCADE_5MODEL_REPORT.md"
    out.write_text("\n".join(L))
    print("WROTE", out, f"({len(L)} lines); models={len(MODELS)}")


if __name__ == "__main__":
    main()
