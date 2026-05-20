# Vergabepilot — Phase 1

**LLM-driven scraper generation for German public-procurement portals.**

Phase 1 is the `feedback_loop` block from the system architecture: given a
tender-portal URL, an LLM writes a Python scraper, a static validator checks
it for unsafe code, a sandbox runs it, and the loop retries on failure. See
[`ARCHITECTURE.md`](ARCHITECTURE.md) for how this fits into the full pipeline
(FastAPI / Celery / Phase 2 CUA / Phase 3 cascade).

```
URL ──► generator ──► validator ──┬──► executor (subprocess sandbox)  ──► evaluator
                                  │       (RLIMIT_AS + timeout)
                                  └──► docker_sandbox (Docker container) ──► evaluator
                                          (read-only fs, cap-drop, --pids-limit, …)
                                            │
                                            └── feedback ──► generator (retry)
```

Two sandbox flavours ship side-by-side:
- **`executor.py`** — fast subprocess sandbox using `RLIMIT_AS` + wall-clock timeout. No Docker required. Good default; what `run.py` uses.
- **`docker_sandbox.py`** — full Docker isolation. Stronger boundary (read-only root fs, dropped Linux caps, isolated network, non-root user). Use when you don't fully trust the LLM-generated code, or when running it in production / CI.

---

## Quickstart (subprocess sandbox)

```bash
# 1. Install
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # only if you'll use multi_llm_evaluator / inspect_*

# 2. Configure
cp .env.example .env
# then edit .env and put your real OPENROUTER_API_KEY

# 3. Run on the bundled CSV (15.9k tender URLs)
python run.py --limit 5            # try the first 5 URLs end-to-end
```

Downloaded documents land in `./downloads/<domain>/<row_id>/`, generated
scraper code lands in `./generated_scrapers/<domain>/<row_id>/attempt_*.py`,
and a JSONL log of every attempt lands in `./results/run_results.jsonl`.

## Quickstart (Docker sandbox)

```bash
# 1. One-time: build the sandbox image
python docker_sandbox.py build

# 2. Run a scraper in the container (auto-generates if missing)
python docker_sandbox.py run generated_scrapers \
    "https://www.evergabe-online.de/search.html"

# 3. With auto-regenerate on failure (up to 3 retries)
python docker_sandbox.py run generated_scrapers \
    "https://www.evergabe-online.de/search.html" \
    --regenerate-on-fail --max-retries 3

# 4. Run the security tests against the sandbox
python docker_sandbox.py test
```

---

## Layout

| File | Purpose |
|------|---------|
| `generator.py`            | LLM client + prompt-building + scraper generation/regeneration/modification. CLI: `python generator.py generate \| regenerate \| modify`. **Prompt-injection-defended**: scraped content is fenced inside `<untrusted_html>` with closing-tag sanitization. **HTTP headers are ASCII-sanitized** to prevent stray non-ASCII chars from crashing the request. |
| `validator.py`            | **Standalone AST static-safety check.** Rejects forbidden imports/calls before any code runs. CLI: `python validator.py scraper.py [scraper2.py ...] [--quiet]`. Exit code 0 if all safe, 1 if any unsafe — useful in CI. |
| `executor.py`             | Sandboxed subprocess runner with `RLIMIT_AS` memory cap and wall-clock timeout. Re-exports `validate` from `validator.py` so `from executor import validate` still works. CLI: `python executor.py run <scraper.py> <url>` |
| `docker_sandbox.py`       | **Hardened Docker sandbox.** Runs scraper code in an isolated container: read-only root fs, dropped capabilities, no privilege escalation, CPU/memory/PID caps, restricted network, non-root user. Auto-generates the scraper via `generator.py` if missing, and can `--regenerate-on-fail`. CLI: `python docker_sandbox.py {build \| run \| test}`. |
| `Dockerfile.sandbox`      | Image used by `docker_sandbox.py`: Python 3.12 + Playwright Chromium, non-root `sandbox` user. Build with `python docker_sandbox.py build`. |
| `evaluator.py`            | Grades a `run_results.jsonl` against ground-truth. |
| `multi_llm_evaluator.py`  | Benchmarks N URLs × M models in parallel; produces markdown / CSV / JSON reports. |
| `run.py`                  | **End-to-end runner (subprocess sandbox).** Reads `data/publications.csv`, runs the full loop per URL, retries up to 3×. **Saves every generated scraper attempt** under `generated_scrapers/<domain>/<row_id>/attempt_<n>.py`. |
| `models.py`               | Single source of truth for the cheap-model menu (23 OpenRouter models across free / ultra-cheap / cheap / mid tiers). Imported by `generator.py` (cost table) and `multi_llm_evaluator.py` (benchmark targets). |
| `llm_client.py`           | (Folded in from v1) Synchronous OpenRouter wrapper with **budget guard** — warns at 80%, hard-stops at 100% of `LLM_BUDGET`. Use this when you want a generic chat client outside the scraper-generation flow. |
| `llm_client_demo.py`      | Tiny worked example for `llm_client.OpenRouterClient`. |
| `audit_report.py` / `build_report.py` / `pick_urls.py` | Reporting + URL-selection utilities. |
| `scraper_*.py`            | Hand-written reference scrapers (used as ground-truth comparators). |
| `inspect_*.py` / `debug_*.py` | One-off debugging scripts for specific portals. |
| `test_*.py`               | Pytest suite — validator (38 tests), prompt-injection defenses (22 tests), scraper smoke tests. |
| `data/publications.csv`   | ~15.9k tender publications (id, url, domain, state, error). Source CSV for `run.py`. |
| `results/run_results.jsonl` | Sample output from a previous run, for inspection. |

---

## Picking a model

The cheap-model menu is curated in `models.py` (23 models, four tiers).
List it without running anything:

```bash
python run.py --list-models
```

Pick one for a single run:

```bash
python run.py --model openrouter/free --limit 5            # free auto-router
python run.py --model deepseek/deepseek-chat --limit 5     # ~$0.28 / 1M out
python run.py --model google/gemini-2.5-flash-lite --limit 5
```

Or set it once in `.env`:

```env
LLM_MODEL=google/gemini-2.5-flash
```

The CLI flag wins over `.env`. Cost estimates are computed per-model from
`models.cost_table()`; whatever id you pass, pricing should resolve.

---

## Where the generated code lands

Every LLM-generated scraper attempt — successful or failed — is written to
disk so you can inspect what the model produced:

```
generated_scrapers/
  www.example.com/
    7292f6ed-…/
      attempt_1.py          ← failed (validator rejected it, or 0 docs)
      attempt_2.py          ← failed
      attempt_3_OK.py       ← winner (suffix _OK marks it)
```

Each file has a docstring header with `row_id`, `domain`, `model`, `cost`,
`status`, and the error if any. The file is still valid Python — copy it
into `executor.py run …` if you want to re-run a winning scraper later.

The list of saved paths also lands in each row of `results/run_results.jsonl`
under the `scrapers` key.

---

## Two LLM clients — what's the difference?

This repo merges two earlier codebases. They each ship an OpenRouter client
because they were written for different jobs:

| | `generator.LLMClient` | `llm_client.OpenRouterClient` |
|---|---|---|
| Style                  | async (`httpx`)              | sync (`requests`) |
| Used by                | the scraper-generation pipeline (`generator.py`, `run.py`, `multi_llm_evaluator.py`) | ad-hoc scripts, model probing, the demo |
| Cost source            | OpenRouter's billed `usage.cost` field (exact)         | local price table per 1k tokens (configurable in `.env`) |
| Budget enforcement     | none                          | warn at 80%, raise `BudgetExceededError` at 100% |
| Multi-model            | yes (model passed per call)   | yes (model passed per call) |

Both read `OPENROUTER_API_KEY` from `.env`. Use `LLMClient` for the pipeline,
`OpenRouterClient` when you want a hard-stop on spend.

---

## Common commands

```bash
# See the cheap-model menu (no API call)
python run.py --list-models

# Full run on the bundled CSV (drop --limit to process all 15.9k rows)
python run.py --limit 10

# Pick a specific model (overrides $LLM_MODEL)
python run.py --limit 5 --model openrouter/free                  # free, auto-routed
python run.py --limit 5 --model deepseek/deepseek-chat           # cheapest serious option
python run.py --limit 5 --model openai/gpt-4.1-mini              # default in .env

# Re-process only rows that previously FAILED
python run.py --failed --limit 50

# One-off URL, no CSV
python run.py --url "https://www.evergabe-online.de/tenderdetails.html?id=12345"

# ── Generator standalone ─────────────────────────────────────────────────
# Just generate code (no execution) — handy for prompt iteration
python generator.py generate "https://example.com/tenders"
# Regenerate after a failure with feedback
python generator.py regenerate "https://example.com/tenders" \
    --iteration 2 --outcome execution_failed --error "TimeoutError ..."
# Modify an existing scraper with a free-text instruction
python generator.py modify ./generated_scrapers/scraper_example_com.py \
    --instruction "Add pagination handling and dedupe filenames"

# ── Validator standalone (CI-friendly) ───────────────────────────────────
python validator.py generated_scrapers/*.py            # check all
python validator.py scraper_evergabe.py --quiet        # only print failures
# exits 0 if all safe, 1 if any unsafe

# ── Subprocess sandbox (executor.py) ─────────────────────────────────────
python executor.py run generated_scrapers/www.example.com/<row_id>/attempt_3_OK.py \
    "https://example.com/tenders"

# ── Docker sandbox (stronger isolation) ──────────────────────────────────
python docker_sandbox.py build                                   # one-time
python docker_sandbox.py run generated_scrapers "https://example.com/tenders"
python docker_sandbox.py run scraper.py "https://example.com" --regenerate-on-fail
python docker_sandbox.py test                                    # security tests

# ── Benchmark several models against several URLs ────────────────────────
python multi_llm_evaluator.py --urls data/publications.csv --limit 5 \
    --models openai/gpt-4o-mini openai/gpt-4.1-mini deepseek/deepseek-chat

# Tests
pytest -q
```

---

## Safety model (high level)

| Risk | Defense |
|---|---|
| Unsafe generated code              | AST validator in `executor.validate()` rejects `eval`, `exec`, `subprocess`, `os.system`, dunder imports, etc. |
| Prompt injection from scraped HTML | Page content is fenced in `<untrusted_html>` and the system prompt treats it as passive data. `generator._fetch_rendered_page_info` extracts a structured summary instead of feeding raw HTML. |
| Runaway resource use               | Subprocess sandbox with wall-clock + memory caps (`SANDBOX_TIMEOUT`, `SANDBOX_MEMORY_MB`). |
| Out-of-control LLM spend           | Optional `llm_client.OpenRouterClient` with `LLM_BUDGET` hard-stop. |

Full details in [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Notes on this merged drop

- The original `Phase-1.zip` shipped with `__pycache__/`, `.pytest_cache/`,
  ~270 MB of `runs/` from prior benchmark sweeps, and `downloads/` containing
  large tender ZIPs. Those have been removed — they're regenerated on every
  run anyway.
- `run.py`'s hardcoded Windows CSV path and inlined API key are gone. The
  default input is now `data/publications.csv` (bundled), and the API key
  must come from `.env`.
- The previously-shipped `.env` contained a real OpenRouter key. It was not
  copied here. **You should rotate that key.** Use `.env.example` as the
  template for your own `.env`.
- `llm_client.py` and `llm_client_demo.py` were folded in from
  `Vergabepilot-v1` because they add the budget-guard feature the canonical
  client doesn't have.
