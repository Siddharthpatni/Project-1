# Full Pipeline (7-Strategy Cascade) — 5-Model Comparison

**Run:** the whole production cascade once per model, `force_model` pinning the LLM step.  
**Dataset:** 20 domains from `data/publications_21_06_2026.xlsx`.  
**Generated:** 2026-06-27 10:31 UTC

---

## Executive Summary

- The **full cascade** (EXISTING → DETERMINISTIC → ADAPTIVE → LLM_GENERATED → LEARNED_ROUTE → CUA → MANUAL) was run end-to-end for each model.
- Range: **7–13/20** solved across models; best: `llama-4-maverick` (13/20).
- Unlike the pure-LLM benchmark (3/20), the cascade reaches **7–13/20** because the free deterministic path grabs DTVP ZIPs and **CUA visually logs into** several vendor portals.
- **Key caveat — the spread is mostly noise, not model quality.** The `LLM-generated` step (the only part `force_model` changes) won **0 domains outright across all five runs** — the free strategies and the CUA always resolved the winnable domains first. The 7–13 range is therefore driven mainly by **CUA's run-to-run stochasticity** (a visual agent gives slightly different results each attempt), not by which LLM was pinned.
- **Takeaway:** for *this* pipeline, the choice among these cheap models barely moves full-system success — the deterministic + CUA + manual strategies do the heavy lifting. Model choice matters far more in the pure-LLM path (see the companion report).

---

## 1. Model Leaderboard (full cascade)

| Rank | Model (as the LLM step) | Solved | Rate | Winning strategies |
|---|---|---|---|---|
| 1 | `llama-4-maverick` | 13/20 | **65%** | CUA 7, Deterministic 2, Manual 2, Existing 1, Adaptive 1 |
| 2 | `gemini-2.5-flash-lite` | 10/20 | **50%** | CUA 6, Deterministic 2, Adaptive 1, Existing 1 |
| 3 | `gpt-4.1-nano` | 9/20 | **45%** | CUA 3, Deterministic 2, Manual 2, Existing 1, Adaptive 1 |
| 4 | `deepseek-chat-v3-0324` | 8/20 | **40%** | CUA 3, Deterministic 2, Adaptive 1, Manual 1, Existing 1 |
| 5 | `gpt-4o-mini` | 7/20 | **35%** | CUA 3, Deterministic 2, Existing 1, Adaptive 1 |

---

## 2. Per-Domain Outcome Matrix

Each cell shows the **winning strategy** (or ✗ if all failed).

| Domain | Access | gemini-2.5-flash-lite | gpt-4.1-nano | deepseek-chat-v3-0324 | gpt-4o-mini | llama-4-maverick |
|---|---|---|---|---|---|---|
| `ausschreibung.halle.de` | 🟢 | Exist | Exist | Exist | Exist | Exist |
| `ausschreibungen.giz.de` | 🟢 | Determ | Determ | Determ | Determ | Determ |
| `ausschreibungen.kfw.de` | 🔒 | CUA | Manual | CUA | CUA | Manual |
| `ausschreibungen.landbw.de` | 🟢 | Determ | Determ | Determ | Determ | Determ |
| `beschaffungen.barmer.de` | 🔒 | ✗ | ✗ | ✗ | ✗ | ✗ |
| `bieter.ehealth-evergabe.de` | 🔒 | CUA | CUA | ✗ | CUA | CUA |
| `bieterportal.dfg.de` | 🔒 | ✗ | ✗ | ✗ | ✗ | CUA |
| `bieterportal.dfg.e-va.eu` | 🔒 | CUA | CUA | CUA | CUA | CUA |
| `bieterportal.noncd.db.de` | 🔒 | ✗ | ✗ | ✗ | ✗ | ✗ |
| `bieterportal.pd-g.e-va.eu` | 🔒 | CUA | Manual | Manual | ✗ | Manual |
| `bieterportal.servicecenter-khs.e-va.eu` | 🔒 | CUA | CUA | CUA | ✗ | CUA |
| `bieterzugang.deutsche-evergabe.de` | 🔒 | ✗ | ✗ | ✗ | ✗ | CUA |
| `bi-medien.de` | 🔒 | Adapt | Adapt | Adapt | Adapt | Adapt |
| `box.fu-berlin.de` | ⚫ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `bund.vergabe24.de` | 🟢 | ✗ | ✗ | ✗ | ✗ | ✗ |
| `deutsche-rentenversicherung-bund.de` | 🔒 | ✗ | ✗ | ✗ | ✗ | ✗ |
| `ec.europa.eu` | 🔒 | CUA | ✗ | ✗ | ✗ | CUA |
| `eliagroup.sharepoint.com` | ⚫ | ✗ | ✗ | ✗ | ✗ | ✗ |
| `eom-vp-prod.ai-hosting.de` | 🔒 | ✗ | ✗ | ✗ | ✗ | ✗ |
| `eu.eu-supply.com` | ⚫ | ✗ | ✗ | ✗ | ✗ | CUA |

Legend: 🟢 public · 🔒 vendor-login · ⚫ deleted/expired · Determ=deterministic ZIP · Exist=cached scraper · Adapt=adaptive heuristic · LLM=LLM-generated · Route=learned CUA route · CUA=visual agent · Manual=hand-written

---

## 3. Which Strategy Did the Work?

Total wins by strategy, summed across all five model-runs:

| Strategy | Wins (of all model-runs) | Model-dependent? |
|---|---|---|
| CUA | 22 | no |
| Deterministic | 10 | no |
| Adaptive | 5 | no |
| Existing | 5 | no |
| Manual | 5 | no |

The free **deterministic** path and the **CUA** visual agent carry the cascade; only **LLM-generated** wins vary with the chosen model.

---

## 4. Success by Access Category

| Access category | Domains | Avg solved across models |
|---|---|---|
| 🟢 Public / scrapeable | 4 | 3.0/4 |
| 🔒 Vendor-login portal | 13 | 6.2/13 |
| ⚫ Deleted / expired | 3 | 0.2/3 |

The cascade reliably clears **public** portals and cracks a chunk of **vendor-login** ones via CUA; **deleted/expired** URLs remain unrecoverable for every model (the document is gone).

---

## 5. Caveats

- **Per-model isolation:** before each model's run, benchmark-generated LLM scrapers + learned routes for these 20 domains were cleared and the Redis circuit-breakers/rate-limiters flushed, so one model can't win for another via a cached scraper. Hand-written `manual` scrapers are a shared baseline (model-independent).
- **CUA uses a fixed vision model** (not `force_model`) **and is stochastic** — a visual agent produces slightly different results each attempt, so its win count varies run-to-run independently of the model. This is the main source of the leaderboard spread, so treat small rank differences as noise.
- **Live-portal variance:** availability and latency vary by the minute; expired notices (HTTP 404) can differ from the pure-LLM run done on a different day.

---

*Companion: [`LLM_BENCHMARK_REPORT.md`](LLM_BENCHMARK_REPORT.md) (pure-LLM, no cascade). Raw data: [`cascade_5models_results.json`](cascade_5models_results.json).*