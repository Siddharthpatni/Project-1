# Architecture

## High-level (target system)

The diagram below is the **intended end-state** of Vergabepilot. Phase 1 —
the contents of this directory — is the leftmost building block. Phases 2
and 3 and the API/queue layer are scoped for later milestones.

```
                        ┌──────────────┐
                        │  Next.js UI  │
                        └──────┬───────┘
                               │ HTTP
                        ┌──────▼───────┐
                        │  FastAPI     │
                        │  /api/jobs   │
                        │  /api/...    │
                        └──────┬───────┘
                               │ enqueue
                        ┌──────▼───────┐         ┌──────────┐
                        │  Celery      │◀────────│  Redis   │
                        │  worker pool │         └──────────┘
                        └──────┬───────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
┌───────▼──────┐    ┌──────────▼──────────┐    ┌──────▼──────┐
│ Phase 3      │    │ Phase 1   ◀── you   │    │ Phase 2     │
│ pipeline.py  │───▶│   are here          │───▶│ orchestrator│
│ (cascade)    │    │  ↳ generator        │    │ ↳ Playwright│
│              │    │  ↳ validator        │    │     CUA     │
│              │    │  ↳ executor(sandbox)│    │             │
│              │    │  ↳ evaluator        │    │             │
└──────┬───────┘    └─────────────────────┘    └─────────────┘
       │
   ┌───▼────┐    ┌──────────┐
   │ MinIO  │    │ Postgres │
   │ (S3)   │    │ (meta)   │
   └────────┘    └──────────┘
```

## Status of this milestone

| Component | Status | Notes |
|---|---|---|
| Phase 1 (LLM scraper loop) | ✅ Implemented | This directory. Standalone, runnable, tested (60/60). |
| Standalone validator       | ✅ Implemented | `validator.py` — separated from `executor.py`. CLI + library. |
| Docker sandbox             | ✅ Implemented | `docker_sandbox.py` + `Dockerfile.sandbox`. Read-only fs, dropped caps, restricted network, non-root user. Built-in security test suite. |
| Phase 2 (CUA fallback)     | ⏳ Planned    | Playwright + vision-LLM agent, not yet started. |
| Phase 3 (cascade pipeline) | ⏳ Planned    | Routes URLs to existing scraper → LLM loop → CUA. |
| FastAPI / Celery / Redis   | ⏳ Planned    | Phase 1 currently runs as a CLI; the loop function is queue-ready. |
| MinIO / Postgres           | ⏳ Planned    | Today: downloads land on local disk, results in JSONL. |

---

## Phase 1 — what's actually in this directory

Phase 1 is delivered as a set of flat top-level Python modules. There is
no `app/` package yet — that arrives when Phase 1 is wrapped by the FastAPI
layer in a later milestone. The files map onto the four boxes inside the
"Phase 1" block in the diagram:

```
URL
 │
 ▼
┌────────────────┐    code     ┌───────────────┐    safe code   ┌────────────────────┐
│  generator.py  │────────────▶│  executor.py  │───────────────▶│  executor.py       │
│  (LLM call)    │             │  validate()   │                │  execute()         │
└────────────────┘             │  (AST check)  │                │  (subprocess +     │
        ▲                      └───────────────┘                │   rlimit sandbox)  │
        │ feedback                                              └─────────┬──────────┘
        │ (error / 0 docs)                                                │
        │                                                                 ▼
┌───────┴────────┐                                              ┌────────────────────┐
│   run.py       │◀─────────────────────────────────────────────│  evaluator.py      │
│   (loop +      │              outcome / metrics               │  (recall vs truth, │
│    retries)    │                                              │   used post-hoc)   │
└────────────────┘                                              └────────────────────┘
```

### Module layout (current)

| File | Role | Notes |
|---|---|---|
| `generator.py`           | LLM client, prompt templates, scraper generation/regeneration/modification. | Contains `LLMClient`, `ScraperGenerator`, `build_generation_prompt`, `build_feedback_prompt`, `build_modify_prompt`. The OpenRouter client is co-located here, not in a separate `core.llm_client` module. HTTP headers are ASCII-sanitized to prevent stray non-ASCII chars from crashing the request. |
| `validator.py`           | **Standalone** AST-based static safety check. | Exposes `validate(code) -> ValidationResult`, `validate_file(path)`, `FORBIDDEN_IMPORTS`, `FORBIDDEN_CALLS`, `REQUIRED_FUNCTION`. Has its own CLI for CI usage. |
| `executor.py`            | Subprocess sandbox + result capture. | Exposes `validate(code)` (re-exported from `validator.py` for backward compatibility) and `execute(code, url) -> ExecutionResult`. Sandbox uses `subprocess.Popen` with `preexec_fn` setting `RLIMIT_AS` and `RLIMIT_CORE` (Unix) and a wall-clock timeout (all platforms). |
| `docker_sandbox.py`      | **Hardened Docker sandbox.** Runs scraper code in an isolated container. | Read-only root fs, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, non-root user, `--memory`/`--cpus`/`--pids-limit`, tmpfs `/tmp`. Auto-invokes `generator.py` if the scraper file is missing. Optional `--regenerate-on-fail`. Includes built-in security test suite (`run_security_tests`). |
| `Dockerfile.sandbox`     | Image used by `docker_sandbox.py`. | Python 3.12-slim + Playwright Chromium + non-root `sandbox` user. |
| `evaluator.py`           | Grades a `run_results.jsonl` against a ground-truth CSV. | Used post-hoc, not in the live loop. |
| `multi_llm_evaluator.py` | Benchmarks N URLs × M models in parallel; emits markdown / CSV / JSON reports. | Uses Playwright to capture per-URL ground truth. Wired to `models.py`. |
| `run.py`                 | **Loop driver.** Reads a CSV of URLs and runs `generate → validate → execute → retry-with-feedback` per row, up to 3 retries. | Plays the role of the `feedback_loop` box in the diagram. **Saves every generated attempt** to `generated_scrapers/<domain>/<row_id>/attempt_<n>.py` (suffix `_OK` for the winner). |
| `models.py`              | Curated cheap-model menu (23 OpenRouter models, 4 tiers). | Single source of truth for `generator.COST_PER_MILLION_TOKENS` and `multi_llm_evaluator.MODELS`. |
| `llm_client.py`          | Standalone synchronous OpenRouter client with budget guard. | Independent of the generation pipeline. Used by ad-hoc scripts and `llm_client_demo.py`. Hard-stops at `LLM_BUDGET`. |
| `scraper_*.py`           | Hand-written reference scrapers. | Used for ground-truth comparison and as worked examples. |
| `data/publications.csv`  | 15.9k tender URLs (id, url, domain, state, error). | Default input for `run.py`. |
| `test_validator.py`, `test_prompt_injection.py`, `test_scraper.py`, `test_brandenburg_download.py` | Pytest suite. | 60/60 tests pass. Validator has 38 tests; prompt-injection has 22. |

### Mapping to the target package layout

When Phase 1 is folded into the larger system, the files above will move
without changing their public functions:

| Today                         | Future home (planned)                          |
|-------------------------------|------------------------------------------------|
| `generator.py`                | `app.phase1_llm_scraper.generator`             |
| `executor.py` (`validate`)    | `app.phase1_llm_scraper.validator`             |
| `executor.py` (`execute`, sandbox helpers) | `app.phase1_llm_scraper.executor` + `app.core.sandbox` |
| `evaluator.py`                | `app.phase1_llm_scraper.evaluator`             |
| `run.py` (`process_url` loop) | `app.phase1_llm_scraper.feedback_loop.run_feedback_loop` |
| `LLMClient` (in `generator.py`) + `llm_client.py` | merged into `app.core.llm_client` |
| (not yet implemented)         | `app.core.security` (`detect_prompt_injection`, `is_url_allowed`, `sanitize_web_content`) |
| (not yet implemented)         | `app.core.storage` (MinIO/S3 wrapper)          |
| (not yet implemented)         | `app.api.routes_*`, `app.workers.celery_app`, `app.workers.tasks` |

The `run_feedback_loop` extraction is the only refactor that affects
public API; everything else is a rename / move.

---

## Data flow — current Phase 1 (CLI)

1. `python run.py [--limit N | --url URL | --failed]` loads URLs from
   `data/publications.csv` (or a single URL).
2. For each URL, `process_url()` runs the loop:
   1. **Generate** — `ScraperGenerator.generate(url)` calls the LLM via
      `LLMClient`. The page is rendered with Playwright and a structured
      summary (title, headings, link hrefs, button texts) is fenced inside
      `<untrusted_html>` in the prompt.
   2. **Validate** — `executor.validate(code)` parses the result with `ast`
      and rejects forbidden imports (`subprocess`, `ctypes`, `socket`,
      `multiprocessing`) and forbidden calls (`eval`, `exec`, `compile`,
      `__import__`, `os.system`, `os.popen`, `subprocess.*`, `socket.socket`,
      `shutil.rmtree`). Requires a `scrape(url, output_dir)` entry point.
   3. **Execute** — `executor.execute(code, url, keep_downloads=...)` writes
      the code to a temp dir and spawns `python` as a subprocess with
      `preexec_fn` setting `RLIMIT_AS` (memory cap) and `RLIMIT_CORE=0`,
      plus a wall-clock timeout. stdout/stderr are captured; downloaded
      files are collected from a temp working dir.
   4. **Decide** — if files were downloaded → done. If not, build a feedback
      prompt with the (truncated) error and loop back to step 1, up to
      `MAX_RETRIES = 3`.
3. Results append to `results/run_results.jsonl`. Documents land in
   `downloads/<domain>/<row_id>/`.

## Data flow — target system (Phase 3 cascade, future)

1. Client `POST /api/jobs` with one or more URLs.
2. API persists `Job` + `JobItem` rows, enqueues `process_job_task`.
3. Worker picks up the task, calls `pipeline.process_url` per item.
4. Cascade:
   - **Existing scraper**: lookup `ScraperTemplate` by domain → if found, run sandboxed.
   - **LLM-generated**: `feedback_loop.run_feedback_loop` (this directory's logic).
     On success, the code is promoted into the registry.
   - **CUA fallback**: `orchestrator.run_agent("playwright_cua")` — vision-LLM + Playwright loop.
5. Downloaded files are uploaded to MinIO; `Document` rows are created.
6. UI polls `GET /api/jobs/{id}` for live status.

---

## Safety model (Phase 1, what's implemented today)

| Risk | Defense | Where |
|------|---------|-------|
| Unsafe generated code            | AST static check | `validator.validate()` — rejects forbidden imports/calls before execution. Also runs as a CLI for CI. |
| Unsafe generated code (runtime, lightweight) | Subprocess + rlimit + restricted env | `executor.execute()` via `_build_preexec_fn(memory_mb)` + `subprocess.Popen` timeout. Used by `run.py`. |
| Unsafe generated code (runtime, hardened) | Docker container | `docker_sandbox.run_in_docker()`: read-only root fs, `--cap-drop=ALL`, `--security-opt=no-new-privileges`, non-root user, `--memory`/`--cpus`/`--pids-limit=100`, tmpfs `/tmp` (`noexec,nosuid,size=64m`). Includes a built-in `run_security_tests()` suite. |
| Prompt injection from web content | Structural separation | Page content fenced in `<untrusted_html>…</untrusted_html>` with explicit "passive data" instruction. The closing tag is escaped in user input so it can't be terminated early. See `generator.build_generation_prompt`. |
| Prompt injection (LLM still emits dangerous code) | AST validator as second line | Even a successful injection has to pass `validator.validate()` to run. Covered by `test_prompt_injection.py` (22 tests). |
| Non-ASCII chars in HTTP headers | Header sanitization | `LLMClient.chat` runs every header value through `.encode("ascii","ignore").decode("ascii")` so a stray en-dash or smart-quote in a copy-pasted constant can't crash `httpx`. |
| Runaway resource use (subprocess) | Wall-clock + memory caps | `SANDBOX_TIMEOUT` (default 120s) + `SANDBOX_MEMORY_MB` (default 512) in `.env`. |
| Runaway resource use (Docker)     | Container limits | `--memory={N}m --memory-swap={N}m --cpus=1 --pids-limit=100`, plus wall-clock kill via `subprocess.Popen.kill()`. |
| Out-of-control LLM spend          | Optional budget guard | `llm_client.OpenRouterClient` — warn at 80%, hard-stop at 100% of `LLM_BUDGET`. **Not** wired into `LLMClient` in `generator.py`; opt-in for ad-hoc scripts. |
| **SSRF / unauthorized hosts**     | ⚠️ Not yet implemented | Planned as `core.security.is_url_allowed` (private-net allowlist). Today, any URL the user passes is fetched. Docker sandbox does limit the *outbound* network the scraper can reach via Docker's default bridge, but does not validate the *user-supplied* target URL. |

## Prompt-injection mitigation checklist

| # | Control | Status |
|---|---------|--------|
| 1 | Scraped content wrapped in `<untrusted_html>` XML fence in every LLM prompt; system prompt instructs the model to treat it as passive data | ✅ Implemented (`generator.py` lines ~174–179) |
| 2 | Test suite covers known injection payloads (role-switch, instruction-override, code-fence escape) | ✅ Implemented (`test_prompt_injection.py`) |
| 3 | `GENERATION_USER_PROMPT` uses a Playwright-rendered structured page summary (`{page_info}`) instead of raw HTML | ✅ Implemented (`generator._fetch_rendered_page_info`) |
| 4 | `</untrusted_html>` tokens in scraped content are escaped before interpolation, preventing fence breakout | ✅ Implemented (`generator.py` line ~245) |
| 5 | `FEEDBACK_PROMPT` does not echo raw scraped content — only error strings and counters from the sandbox | ✅ Implemented |
| 6 | Generated stderr is truncated (≈2 000 chars) before going back into the feedback prompt | ✅ Implemented |

### Mitigation strategy

Scraped web content is **untrusted at all layers**:

1. **Prompt-level fence** — every call to the LLM wraps scraped data in
   `<untrusted_html>…</untrusted_html>`. The system prompt opens with an
   explicit "passive data" instruction. The closing fence is sanitized in
   the user input so the model can't be tricked into ending the block
   early. Same pattern as SQL parameterisation: data and instructions
   travel in structurally separate channels.
2. **Structured extraction over raw HTML** — Playwright extracts a typed
   summary (title, button texts, link hrefs, headings, body text). The LLM
   never sees a raw `<script>` or inline event handler; only labelled text
   fields. Eliminates the most common injection vector.
3. **Error-message truncation** — the feedback loop caps `stderr` before
   interpolating it into `FEEDBACK_PROMPT`, preventing a crafted error
   from filling the context window with injected instructions.
4. **AST validator as second line** — even if injection succeeds in
   making the LLM emit a forbidden call, `executor.validate()` rejects
   it before the sandbox ever starts.

## Why this layout

The brief asks for *one file per topic so it's easy for development*. In
this Phase 1 deliverable that's taken literally: each box in the diagram
is one top-level Python file. When Phase 1 is wrapped by the API/queue
layer in a later milestone, the same files move into
`app/phase1_llm_scraper/` and `app/core/` per the mapping table above —
without changing their public functions.
