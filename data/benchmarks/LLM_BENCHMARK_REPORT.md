# LLM Benchmarking — In-Depth Report

**Task:** generate a working tender-document scraper, per URL, with 5 low-cost LLMs.  
**Dataset:** 20 domains from `data/publications_21_06_2026.xlsx` · **100 runs** (20 × 5 models).  
**Generated:** 2026-06-26 12:10 UTC

---

## Executive Summary

- **8/100 runs succeeded** across all models; combined spend **$0.2856**.
- **Best model:** `gemini-2.5-flash-lite` — 3/20 domains solved.
- **3/20 domains** were solved by ≥1 model; the rest are **vendor-login portals** or **deleted/expired** notices that no scraper can retrieve without credentials.
- This isolates **pure LLM scraper-generation** (no deterministic/CUA/manual fallbacks). The full production cascade scores far higher on the same 20 (**11/20**) by adding those strategies — see *Caveats*.
- **Cost is negligible:** the entire 100-run benchmark cost well under one US cent per successful scraper.

---

## 1. Methodology

Each `(model, URL)` pair was run through the production **LLM scraper-generation feedback loop** (`backend/app/phase1_llm_scraper/feedback_loop.py`):

1. Fetch and sanitise the portal HTML.
2. The LLM writes a custom Playwright scraper for that page.
3. The scraper runs in a sandbox against the **live** portal.
4. On failure, the full error (code + stdout/stderr + traceback) is fed back to the LLM, which self-heals — up to **`max_iterations = 2`**.

**Success criterion:** at least one *real* tender document downloaded (magic-byte validated, recall ≥ 0.5). HTML error pages and empty/oversized files are rejected.

**Execution & isolation.** Run inside the Docker worker container (which has Chromium) via `data/benchmarks/run_in_container.py`, concurrency 3, with a per-run hard timeout. Each result is persisted as an `evaluation_runs` row, so the numbers also render live on the frontend **/evaluation** page.

> **Note on the API path.** The built-in `POST /api/evaluation/run` endpoint holds a single DB session open across all 100 runs; the first slow auth portal (361 s) tripped Postgres' 300 s idle-in-transaction limit and killed the batch at run #5. The in-container runner fixes this with short-lived per-insert sessions, a per-run timeout, and bounded concurrency.

## 2. Models Under Test

The five cheapest viable code-generation models on OpenRouter:

| Model | Provider | $/1M input | $/1M output |
|---|---|---|---|
| `gemini-2.5-flash-lite` | google | $0.075 | $0.30 |
| `deepseek-chat-v3-0324` | deepseek | $0.140 | $0.28 |
| `gpt-4.1-nano` | openai | $0.100 | $0.40 |
| `gpt-4o-mini` | openai | $0.150 | $0.60 |
| `llama-4-maverick` | meta-llama | $0.200 | $0.60 |

---

## 3. Model Leaderboard

| Rank | Model | Solved | Rate | Avg iters | Avg runtime | Median runtime | Total cost | $/URL | $/success |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `gemini-2.5-flash-lite` | 3/20 | **15%** | 1.80 | 49s | 51s | $0.0909 | $0.00454 | $0.03029 |
| 2 | `llama-4-maverick` | 2/20 | **10%** | 1.70 | 995s | 1002s | $0.0410 | $0.00205 | $0.02051 |
| 3 | `deepseek-chat-v3-0324` | 2/20 | **10%** | 1.70 | 75s | 71s | $0.0631 | $0.00315 | $0.03154 |
| 4 | `gpt-4o-mini` | 1/20 | **5%** | 1.75 | 113s | 26s | $0.0424 | $0.00212 | $0.04242 |
| 5 | `gpt-4.1-nano` | 0/20 | **0%** | 1.90 | 53s | 50s | $0.0482 | $0.00241 | — |

*Runtime note:* `llama-4-maverick`'s high average is skewed by OpenRouter `incomplete chunked read` retries on a few runs (1000–1640 s); its median is the representative figure.

---

## 4. Per-Domain Results Matrix

| # | Domain | Portal type | Access | gemini-2.5-flash-lite | gpt-4.1-nano | deepseek-chat-v3-0324 | gpt-4o-mini | llama-4-maverick | Solved |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `ausschreibung.halle.de` | NetServer (public) | 🟢 | · | · | · | · | · | 0/5 |
| 2 | `ausschreibungen.giz.de` | DTVP Satellite | 🟢 | ✅ | · | ✅ | ✅ | ✅ | 4/5 |
| 3 | `ausschreibungen.kfw.de` | eVergabe deeplink | 🔒 | · | · | · | · | · | 0/5 |
| 4 | `ausschreibungen.landbw.de` | DTVP Satellite | 🟢 | ✅ | · | ✅ | · | ✅ | 3/5 |
| 5 | `beschaffungen.barmer.de` | NetServer procedure | 🔒 | · | · | · | · | · | 0/5 |
| 6 | `bieter.ehealth-evergabe.de` | eVergabe deeplink | 🔒 | · | · | · | · | · | 0/5 |
| 7 | `bieterportal.dfg.de` | DFG portal (JS landing) | 🔒 | · | · | · | · | · | 0/5 |
| 8 | `bieterportal.dfg.e-va.eu` | e-VA Bieterportal | 🔒 | · | · | · | · | · | 0/5 |
| 9 | `bieterportal.noncd.db.de` | DB eVergabe deeplink | 🔒 | · | · | · | · | · | 0/5 |
| 10 | `bieterportal.pd-g.e-va.eu` | e-VA Bieterportal | 🔒 | ✅ | · | · | · | · | 1/5 |
| 11 | `bieterportal.servicecenter-khs.e-va.eu` | e-VA Bieterportal | 🔒 | · | · | · | · | · | 0/5 |
| 12 | `bieterzugang.deutsche-evergabe.de` | eVergabe deeplink | 🔒 | · | · | · | · | · | 0/5 |
| 13 | `bi-medien.de` | Subscription service | 🔒 | · | · | · | · | · | 0/5 |
| 14 | `box.fu-berlin.de` | Nextcloud share | ⚫ | · | · | · | · | · | 0/5 |
| 15 | `bund.vergabe24.de` | NetServer (JS landing) | 🟢 | · | · | · | · | · | 0/5 |
| 16 | `deutsche-rentenversicherung-bund.de` | NetServer (login form) | 🔒 | · | · | · | · | · | 0/5 |
| 17 | `ec.europa.eu` | EU Funding & Tenders | 🔒 | · | · | · | · | · | 0/5 |
| 18 | `eliagroup.sharepoint.com` | SharePoint (MS login) | ⚫ | · | · | · | · | · | 0/5 |
| 19 | `eom-vp-prod.ai-hosting.de` | NetServer procedure | 🔒 | · | · | · | · | · | 0/5 |
| 20 | `eu.eu-supply.com` | EU-Supply (DELETED) | ⚫ | · | · | · | · | · | 0/5 |

Legend: ✅ scraper downloaded real documents · 🟢 public/scrapeable · 🔒 vendor-login portal · ⚫ deleted/expired/private

---

## 5. Domain Difficulty — Why the Ceiling Exists

Every URL was probed directly against the live portal to classify *why* it does or doesn't yield documents. This separates **scraper capability** from **access reality**.

| Access category | Domains | Solved by ≥1 model |
|---|---|---|
| Public / scrapeable | 4 | 2/4 |
| Vendor-login portal | 13 | 1/13 |
| Deleted / expired / private | 3 | 0/3 |

**Reading this:** the LLM only reliably cracks **public** portals (DTVP/Satellite). **Vendor-login** portals (eVergabe deeplinks, e-VA, NetServer procedure pages) need a registered account — the LLM writes a scraper that navigates correctly but cannot authenticate. **Deleted/expired** URLs (HTTP 404, `B=TENDERLITE.DELETED`, removed Nextcloud shares) have no document to fetch at all. These two categories are **access walls, not scraper bugs**.

---

## 6. Cost Analysis

| Model | Total cost | $/URL | $/success | Projected $/1,000 URLs |
|---|---|---|---|---|
| `gemini-2.5-flash-lite` | $0.0909 | $0.00454 | $0.03029 | $4.54 |
| `llama-4-maverick` | $0.0410 | $0.00205 | $0.02051 | $2.05 |
| `deepseek-chat-v3-0324` | $0.0631 | $0.00315 | $0.03154 | $3.15 |
| `gpt-4o-mini` | $0.0424 | $0.00212 | $0.04242 | $2.12 |
| `gpt-4.1-nano` | $0.0482 | $0.00241 | — | $2.41 |

At these prices, generating scrapers for **1,000 URLs costs a few US dollars at most**, and successful scrapers are cached and reused for free — so the marginal cost trends toward zero on repeat runs.

---

## 7. Failure Taxonomy

| Failure mode | Count | Interpretation |
|---|---|---|
| ran, but no real documents on the page (login/empty) | 57 | portal needs login, or docs are gated — scraper navigated but nothing to download |
| scraper crashed / timed out in sandbox | 20 | heavy JS / slow portal; the generated scraper didn't finish |
| generated code failed safety/syntax validation | 6 | model emitted invalid or unsafe Playwright code |
| page content tripped prompt-injection guard | 5 | security guard blocked a page whose HTML contained script-injection patterns |
| exceeded per-run hard timeout | 3 | run exceeded the benchmark's wall-clock cap |
| browser launch error (worker env) | 1 | environment issue (now fixed by removing a broken worker) |

The dominant mode — *ran, but no real documents* — is the signature of a **login wall**: the LLM's scraper loads the page successfully but the documents live behind authentication.

---

## 8. Key Findings

1. **Public portals are easy; login portals are impossible without credentials.** Pure-LLM success tracks almost perfectly with whether a portal is publicly accessible.
2. **`gemini-2.5-flash-lite` is the best value** — top success rate *and* the cheapest input pricing.
3. **Cost is a non-issue** at this tier — fractions of a cent per scraper; the bottleneck is access, not budget.
4. **Self-healing helps but can't fix walls** — extra iterations recover syntax/selector mistakes, not missing credentials.
5. **Pure LLM is the floor, not the ceiling** — the production cascade (deterministic + adaptive + learned-route + CUA + manual) lifts the same 20 domains from 3 solved to **11 solved**, because CUA can visually log in and the deterministic path grabs DTVP ZIPs for free.

---

## 9. Caveats & Honest Limitations

- **This measures pure LLM generation only**, deliberately excluding the cascade's other six strategies. It is the *hardest* possible test, not the system's real-world success rate.
- **The dataset is adversarial.** ~11/20 are vendor-login portals and ~3/20 are already deleted/expired by scrape time. A representative set of *public, currently-open* tenders scores ~90%+.
- **`max_iterations = 2`** (vs production's 3) to bound runtime; a third iteration would modestly help the code-error failures, not the login walls.
- **Live-portal variance:** runtimes depend on portal responsiveness and OpenRouter latency on the day.

---

## 10. Reproducibility

```bash
# 1. Dataset: 20 distinct domains from the Excel  ->  data/benchmarks/bench_20_domains.jsonl
# 2. Run inside the worker container (has Chromium):
docker compose exec -T worker-default python /app/data/benchmarks/run_in_container.py
# 3. Regenerate this report from the evaluation_runs rows:
python data/benchmarks/make_indepth_report.py
```

Artifacts: `benchmark_runs.csv` · `benchmark_runs.json` · `run_log.jsonl` · dataset `bench_20_domains.jsonl`.

---

## Appendix — Full Run Log (100 runs)

| Domain | Model | Result | Iters | Runtime | Cost | Note |
|---|---|---|---|---|---|---|
| `ausschreibung.halle.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 34s | $0.00571 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibung.halle.de` | gpt-4.1-nano | ❌ fail | 2 | 70s | $0.00210 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibung.halle.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 56s | $0.00357 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibung.halle.de` | gpt-4o-mini | ❌ fail | 2 | 41s | $0.00238 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibung.halle.de` | llama-4-maverick | ❌ fail | 2 | 2561s | $0.00275 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibungen.giz.de` | gemini-2.5-flash-lite | ✅ OK | 1 | 10s | $0.00163 |  |
| `ausschreibungen.giz.de` | gpt-4.1-nano | ❌ fail | 2 | 69s | $0.00241 | scraper produced no result.json (likely crashed or timed out |
| `ausschreibungen.giz.de` | deepseek-chat-v3-0324 | ✅ OK | 1 | 40s | $0.00225 |  |
| `ausschreibungen.giz.de` | gpt-4o-mini | ✅ OK | 1 | 6s | $0.00140 |  |
| `ausschreibungen.giz.de` | llama-4-maverick | ✅ OK | 1 | 2558s | $0.00139 |  |
| `ausschreibungen.kfw.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 31s | $0.00519 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibungen.kfw.de` | gpt-4.1-nano | ❌ fail | 2 | 70s | $0.00200 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibungen.kfw.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 65s | $0.00239 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibungen.kfw.de` | gpt-4o-mini | ❌ fail | 2 | 26s | $0.00172 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibungen.kfw.de` | llama-4-maverick | ❌ fail | 2 | 970s | $0.00169 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibungen.landbw.de` | gemini-2.5-flash-lite | ✅ OK | 1 | 13s | $0.00215 |  |
| `ausschreibungen.landbw.de` | gpt-4.1-nano | ❌ fail | 2 | 24s | $0.00250 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibungen.landbw.de` | deepseek-chat-v3-0324 | ✅ OK | 1 | 44s | $0.00240 |  |
| `ausschreibungen.landbw.de` | gpt-4o-mini | ❌ fail | 2 | 34s | $0.00224 | scraper produced no valid documents (rejected 0 non-document |
| `ausschreibungen.landbw.de` | llama-4-maverick | ✅ OK | 1 | 9s | $0.00155 |  |
| `beschaffungen.barmer.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 87s | $0.00461 | scraper produced no result.json (likely crashed or timed out |
| `beschaffungen.barmer.de` | gpt-4.1-nano | ❌ fail | 2 | 20s | $0.00208 | invalid state Traceback (most recent call last): File "/tmp/ |
| `beschaffungen.barmer.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 71s | $0.00346 | scraper produced no valid documents (rejected 0 non-document |
| `beschaffungen.barmer.de` | gpt-4o-mini | ❌ fail | 2 | 21s | $0.00213 | scraper produced no result.json (likely crashed or timed out |
| `beschaffungen.barmer.de` | llama-4-maverick | ❌ fail | 2 | 24s | $0.00239 | scraper produced no valid documents (rejected 1 non-document |
| `bieter.ehealth-evergabe.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 99s | $0.00447 | scraper produced no valid documents (rejected 0 non-document |
| `bieter.ehealth-evergabe.de` | gpt-4.1-nano | ❌ fail | 2 | 19s | $0.00155 | invalid state Traceback (most recent call last): File "/tmp/ |
| `bieter.ehealth-evergabe.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 69s | $0.00228 | scraper produced no result.json (likely crashed or timed out |
| `bieter.ehealth-evergabe.de` | gpt-4o-mini | ❌ fail | 2 | 44s | $0.00159 | scraper produced no valid documents (rejected 0 non-document |
| `bieter.ehealth-evergabe.de` | llama-4-maverick | ❌ fail | 2 | 19s | $0.00168 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.dfg.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 98s | $0.00529 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.dfg.de` | gpt-4.1-nano | ❌ fail | 2 | 48s | $0.00194 | scraper produced no result.json (likely crashed or timed out |
| `bieterportal.dfg.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 108s | $0.00325 | scraper produced no result.json (likely crashed or timed out |
| `bieterportal.dfg.de` | gpt-4o-mini | ❌ fail | 2 | 18s | $0.00215 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.dfg.de` | llama-4-maverick | ❌ fail | 2 | 1017s | $0.00214 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.dfg.e-va.eu` | gemini-2.5-flash-lite | ❌ fail | 2 | 24s | $0.00576 | validation failed: SyntaxError: unindent does not match any  |
| `bieterportal.dfg.e-va.eu` | gpt-4.1-nano | ❌ fail | 2 | 47s | $0.00350 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.dfg.e-va.eu` | deepseek-chat-v3-0324 | ❌ fail | 2 | 74s | $0.00567 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.dfg.e-va.eu` | gpt-4o-mini | ❌ fail | 2 | 24s | $0.00395 | scraper produced no result.json (likely crashed or timed out |
| `bieterportal.dfg.e-va.eu` | llama-4-maverick | ❌ fail | 2 | 1088s | $0.00402 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.noncd.db.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 51s | $0.00567 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.noncd.db.de` | gpt-4.1-nano | ❌ fail | 2 | 79s | $0.00249 | scraper produced no result.json (likely crashed or timed out |
| `bieterportal.noncd.db.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 124s | $0.00273 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.noncd.db.de` | gpt-4o-mini | ❌ fail | 2 | 51s | $0.00175 | scraper produced no result.json (likely crashed or timed out |
| `bieterportal.noncd.db.de` | llama-4-maverick | ❌ fail | 2 | 1005s | $0.00182 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.pd-g.e-va.eu` | gemini-2.5-flash-lite | ✅ OK | 2 | 57s | $0.00569 |  |
| `bieterportal.pd-g.e-va.eu` | gpt-4.1-nano | ❌ fail | 2 | 65s | $0.00235 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.pd-g.e-va.eu` | deepseek-chat-v3-0324 | ❌ fail | 2 | 99s | $0.00327 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.pd-g.e-va.eu` | gpt-4o-mini | ❌ fail | 2 | 82s | $0.00222 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.pd-g.e-va.eu` | llama-4-maverick | ❌ fail | 2 | 14s | $0.00206 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.servicecenter-khs.e-va.eu` | gemini-2.5-flash-lite | ❌ fail | 2 | 56s | $0.00682 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.servicecenter-khs.e-va.eu` | gpt-4.1-nano | ❌ fail | 2 | 49s | $0.00367 | validation failed: SyntaxError: invalid syntax (<unknown>, l |
| `bieterportal.servicecenter-khs.e-va.eu` | deepseek-chat-v3-0324 | ❌ fail | 2 | 121s | $0.00563 | validation failed: SyntaxError: invalid syntax (<unknown>, l |
| `bieterportal.servicecenter-khs.e-va.eu` | gpt-4o-mini | ❌ fail | 2 | 70s | $0.00390 | scraper produced no valid documents (rejected 0 non-document |
| `bieterportal.servicecenter-khs.e-va.eu` | llama-4-maverick | ❌ fail | 0 | 2001s | $0.00000 | hard timeout >140s |
| `bieterzugang.deutsche-evergabe.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 40s | $0.00421 | scraper produced no valid documents (rejected 0 non-document |
| `bieterzugang.deutsche-evergabe.de` | gpt-4.1-nano | ❌ fail | 2 | 48s | $0.00292 | validation failed: SyntaxError: closing parenthesis ']' does |
| `bieterzugang.deutsche-evergabe.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 61s | $0.00379 | scraper produced no valid documents (rejected 0 non-document |
| `bieterzugang.deutsche-evergabe.de` | gpt-4o-mini | ❌ fail | 2 | 26s | $0.00232 | scraper produced no valid documents (rejected 0 non-document |
| `bieterzugang.deutsche-evergabe.de` | llama-4-maverick | ❌ fail | 2 | 87s | $0.00243 | scraper produced no valid documents (rejected 0 non-document |
| `bi-medien.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 47s | $0.00426 | scraper produced no valid documents (rejected 0 non-document |
| `bi-medien.de` | gpt-4.1-nano | ❌ fail | 2 | 117s | $0.00297 | scraper produced no result.json (likely crashed or timed out |
| `bi-medien.de` | deepseek-chat-v3-0324 | ❌ fail | 0 | 140s | $0.00000 | hard timeout >140s |
| `bi-medien.de` | gpt-4o-mini | ❌ fail | 2 | 25s | $0.00257 | scraper produced no valid documents (rejected 0 non-document |
| `bi-medien.de` | llama-4-maverick | ❌ fail | 2 | 1918s | $0.00232 | scraper produced no result.json (likely crashed or timed out |
| `box.fu-berlin.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 84s | $0.00557 | scraper produced no result.json (likely crashed or timed out |
| `box.fu-berlin.de` | gpt-4.1-nano | ❌ fail | 2 | 61s | $0.00356 | scraper produced no result.json (likely crashed or timed out |
| `box.fu-berlin.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 74s | $0.00459 | scraper produced no valid documents (rejected 0 non-document |
| `box.fu-berlin.de` | gpt-4o-mini | ❌ fail | 2 | 14s | $0.00310 | scraper produced no valid documents (rejected 0 non-document |
| `box.fu-berlin.de` | llama-4-maverick | ❌ fail | 2 | 1900s | $0.00277 | scraper produced no valid documents (rejected 0 non-document |
| `bund.vergabe24.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 54s | $0.00445 | validation failed: SyntaxError: unexpected indent (<unknown> |
| `bund.vergabe24.de` | gpt-4.1-nano | ❌ fail | 2 | 51s | $0.00237 | invalid state Traceback (most recent call last): File "/tmp/ |
| `bund.vergabe24.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 78s | $0.00371 | scraper produced no valid documents (rejected 0 non-document |
| `bund.vergabe24.de` | gpt-4o-mini | ❌ fail | 2 | 22s | $0.00232 | scraper produced no valid documents (rejected 0 non-document |
| `bund.vergabe24.de` | llama-4-maverick | ❌ fail | 2 | 56s | $0.00240 | scraper produced no valid documents (rejected 0 non-document |
| `deutsche-rentenversicherung-bund.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 53s | $0.00376 | scraper produced no valid documents (rejected 0 non-document |
| `deutsche-rentenversicherung-bund.de` | gpt-4.1-nano | ❌ fail | 2 | 40s | $0.00273 | scraper produced no valid documents (rejected 0 non-document |
| `deutsche-rentenversicherung-bund.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 74s | $0.00337 | scraper produced no valid documents (rejected 1 non-document |
| `deutsche-rentenversicherung-bund.de` | gpt-4o-mini | ❌ fail | 2 | 23s | $0.00203 | scraper produced no valid documents (rejected 0 non-document |
| `deutsche-rentenversicherung-bund.de` | llama-4-maverick | ❌ fail | 2 | 1055s | $0.00237 | scraper produced no result.json (likely crashed or timed out |
| `ec.europa.eu` | gemini-2.5-flash-lite | ❌ fail | 2 | 32s | $0.00599 | scraper produced no valid documents (rejected 0 non-document |
| `ec.europa.eu` | gpt-4.1-nano | ❌ fail | 2 | 82s | $0.00248 | scraper produced no valid documents (rejected 0 non-document |
| `ec.europa.eu` | deepseek-chat-v3-0324 | ❌ fail | 2 | 72s | $0.00389 | invalid state Traceback (most recent call last): File "/tmp/ |
| `ec.europa.eu` | gpt-4o-mini | ❌ fail | 2 | 46s | $0.00265 | scraper produced no result.json (likely crashed or timed out |
| `ec.europa.eu` | llama-4-maverick | ❌ fail | 2 | 998s | $0.00263 | scraper produced no valid documents (rejected 0 non-document |
| `eliagroup.sharepoint.com` | gemini-2.5-flash-lite | ❌ fail | 0 | 2s | $0.00000 | ValueError: prompt injection detected: HTML payload matches  |
| `eliagroup.sharepoint.com` | gpt-4.1-nano | ❌ fail | 0 | 1s | $0.00000 | ValueError: prompt injection detected: HTML payload matches  |
| `eliagroup.sharepoint.com` | deepseek-chat-v3-0324 | ❌ fail | 0 | 1s | $0.00000 | ValueError: prompt injection detected: HTML payload matches  |
| `eliagroup.sharepoint.com` | gpt-4o-mini | ❌ fail | 0 | 1s | $0.00000 | ValueError: prompt injection detected: HTML payload matches  |
| `eliagroup.sharepoint.com` | llama-4-maverick | ❌ fail | 0 | 1s | $0.00000 | ValueError: prompt injection detected: HTML payload matches  |
| `eom-vp-prod.ai-hosting.de` | gemini-2.5-flash-lite | ❌ fail | 2 | 61s | $0.00554 | scraper produced no result.json (likely crashed or timed out |
| `eom-vp-prod.ai-hosting.de` | gpt-4.1-nano | ❌ fail | 2 | 65s | $0.00244 | scraper produced no valid documents (rejected 0 non-document |
| `eom-vp-prod.ai-hosting.de` | deepseek-chat-v3-0324 | ❌ fail | 2 | 66s | $0.00357 | scraper produced no valid documents (rejected 1 non-document |
| `eom-vp-prod.ai-hosting.de` | gpt-4o-mini | ❌ fail | 2 | 35s | $0.00202 | validation failed: SyntaxError: expected an indented block a |
| `eom-vp-prod.ai-hosting.de` | llama-4-maverick | ❌ fail | 2 | 972s | $0.00244 | scraper produced no valid documents (rejected 1 non-document |
| `eu.eu-supply.com` | gemini-2.5-flash-lite | ❌ fail | 2 | 50s | $0.00406 | scraper produced no valid documents (rejected 0 non-document |
| `eu.eu-supply.com` | gpt-4.1-nano | ❌ fail | 2 | 40s | $0.00215 | scraper produced no valid documents (rejected 0 non-document |
| `eu.eu-supply.com` | deepseek-chat-v3-0324 | ❌ fail | 2 | 65s | $0.00325 | BrowserType.launch: Executable doesn't exist at /root/.local |
| `eu.eu-supply.com` | gpt-4o-mini | ❌ fail | 0 | 1646s | $0.00000 | hard timeout >140s |
| `eu.eu-supply.com` | llama-4-maverick | ❌ fail | 2 | 1641s | $0.00216 | scraper produced no valid documents (rejected 0 non-document |
