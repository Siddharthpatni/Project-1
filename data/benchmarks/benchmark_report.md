# LLM Benchmark — 20 Domains × 5 Low-Cost LLMs

*Generated 2026-06-25 16:49 UTC · source: `data/publications_21_06_2026.xlsx` · 100 runs (20 domains × 5 models)*

## Method

Each URL was passed to the production **LLM scraper-generation feedback loop** (`phase1_llm_scraper.feedback_loop.run_feedback_loop`, `max_iterations=2`): the model reads the portal HTML, writes Playwright code, the sandbox runs it against the **live** portal, and the model self-heals from the error once. A run counts as **success** only if real documents were downloaded (recall ≥ 0.5). Run **inside the Docker worker container** (which has Chromium) by `data/benchmarks/run_in_container.py`; each result is written as an `evaluation_runs` row, so the results also appear on the frontend **/evaluation** page. No cascade fallbacks (deterministic/CUA/manual) were used — this isolates pure LLM capability.

> **Why not the `/api/evaluation/run` endpoint?** The batch endpoint holds one DB session open across all 100 runs; the first auth-gated portal (`barmer.de`) ran 361 s and tripped Postgres' 300 s `idle-in-transaction` limit, killing the task at run #5. The in-container runner fixes this with a per-run hard timeout, a fresh short-lived DB session per insert, bounded iterations, and concurrency 3 (gentle on OpenRouter).

> **Limitation:** the 140 s per-run timeout is enforced on the awaiting coroutine, but blocking work inside threaded sandbox/LLM-retry paths can overrun it — a few `llama-4-maverick` runs reached 1000–1640 s due to OpenRouter `incomplete chunked read` retries. This inflates that model's avg runtime but did not stall the overall run.

## Model Leaderboard

| Rank | Model | List $/1M (in/out) | Success | Rate | Avg iters | Avg runtime | Total cost | $/URL |
|---|---|---|---|---|---|---|---|---|
| 1 | `gemini-2.5-flash-lite` | 0.075/0.3 | 3/20 | **15%** | 1.80 | 49.2s | $0.0909 | $0.004543 |
| 2 | `llama-4-maverick` | 0.2/0.6 | 2/20 | **10%** | 1.70 | 994.7s | $0.0410 | $0.002051 |
| 3 | `deepseek-chat-v3-0324` | 0.14/0.28 | 2/20 | **10%** | 1.70 | 75.1s | $0.0631 | $0.003154 |
| 4 | `gpt-4o-mini` | 0.15/0.6 | 1/20 | **5%** | 1.75 | 112.7s | $0.0424 | $0.002121 |
| 5 | `gpt-4.1-nano` | 0.1/0.4 | 0/20 | **0%** | 1.90 | 53.2s | $0.0482 | $0.002411 |

**Totals:** 8/100 successful runs across all models · combined spend **$0.2856**.

## Per-Domain Success Matrix

| # | Domain | gemini-2.5-flash-lite | gpt-4.1-nano | deepseek-chat-v3-0324 | gpt-4o-mini | llama-4-maverick | wins |
|---|---|---|---|---|---|---|---|
| 1 | `ausschreibung.halle.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 2 | `ausschreibungen.giz.de` | ✅ | ❌ | ✅ | ✅ | ✅ | 4/5 |
| 3 | `ausschreibungen.kfw.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 4 | `ausschreibungen.landbw.de` | ✅ | ❌ | ✅ | ❌ | ✅ | 3/5 |
| 5 | `beschaffungen.barmer.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 6 | `bieter.ehealth-evergabe.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 7 | `bieterportal.dfg.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 8 | `bieterportal.dfg.e-va.eu` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 9 | `bieterportal.noncd.db.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 10 | `bieterportal.pd-g.e-va.eu` | ✅ | ❌ | ❌ | ❌ | ❌ | 1/5 |
| 11 | `bieterportal.servicecenter-khs.e-va.eu` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 12 | `bieterzugang.deutsche-evergabe.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 13 | `bi-medien.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 14 | `box.fu-berlin.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 15 | `bund.vergabe24.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 16 | `deutsche-rentenversicherung-bund.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 17 | `ec.europa.eu` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 18 | `eliagroup.sharepoint.com` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 19 | `eom-vp-prod.ai-hosting.de` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |
| 20 | `eu.eu-supply.com` | ❌ | ❌ | ❌ | ❌ | ❌ | 0/5 |

**3/20 domains** were solved by at least one model; **17/20** were unsolved by every model (typically auth-gated / login-walled portals).

## Common Failure Reasons

| Failure reason (note prefix) | Count |
|---|---|
| scraper produced no valid documents (rejected 0 non-document | 53 |
| scraper produced no result.json (likely crashed or timed out | 16 |
| validation failed | 6 |
| ValueError | 5 |
| scraper produced no valid documents (rejected 1 non-document | 4 |
| invalid state
Traceback (most recent call last) | 4 |
| hard timeout >140s | 3 |
| BrowserType.launch | 1 |

---

*Artifacts: [`benchmark_runs.csv`](benchmark_runs.csv) · [`benchmark_runs.json`](benchmark_runs.json) · dataset [`bench_20_domains.jsonl`](bench_20_domains.jsonl)*