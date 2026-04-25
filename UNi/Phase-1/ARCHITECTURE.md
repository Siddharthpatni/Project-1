# Architecture

## High-level

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
│ Phase 3      │    │ Phase 1             │    │ Phase 2     │
│ pipeline.py  │───▶│ feedback_loop.py    │───▶│ orchestrator│
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

## Module layout

| Module                            | Purpose |
|-----------------------------------|---------|
| `app.api.routes_*`                | REST endpoints — one file per resource |
| `app.phase1_llm_scraper.*`        | LLM-based scraper generation pipeline |
| `app.phase2_cua.*`                | Computer-use agents |
| `app.phase3_integration.*`        | Cascaded pipeline + reusable scraper registry + versioning |
| `app.core.llm_client`             | OpenRouter / Anthropic / OpenAI unified client |
| `app.core.storage`                | S3 / MinIO wrapper |
| `app.core.sandbox`                | Subprocess sandbox for untrusted code |
| `app.core.security`               | Prompt-injection detection + URL allowlisting |
| `app.workers.celery_app`          | Celery instance + beat schedule |
| `app.workers.tasks`               | Task definitions (job processing, evaluation, CUA, versioning) |

## Data flow for a single URL (Phase 3 cascade)

1. Client `POST /api/jobs` with one or more URLs.
2. API persists `Job` + `JobItem` rows, enqueues `process_job_task`.
3. Worker picks up the task, calls `pipeline.process_url` per item.
4. Cascade:
   - **Existing scraper**: lookup `ScraperTemplate` by domain → if found, run sandboxed.
   - **LLM-generated**: `feedback_loop.run_feedback_loop` (generate → validate → execute → evaluate → retry).
     On success, the code is promoted into the registry.
   - **CUA fallback**: `orchestrator.run_agent("playwright_cua")` — vision LLM + Playwright loop.
5. Downloaded files are uploaded to MinIO; `Document` rows are created.
6. UI polls `GET /api/jobs/{id}` for live status.

## Safety model (Phase 1)

| Risk | Defense |
|------|---------|
| Unsafe generated code | `phase1_llm_scraper.validator` (AST static check) + `core.sandbox` (subprocess + rlimit + restricted env) |
| Prompt injection from web content | `core.security.detect_prompt_injection` + `sanitize_web_content` |
| SSRF / unauthorized hosts | `core.security.is_url_allowed` (private-net allowlist) |
| Runaway resource use | wall-clock + memory caps in sandbox |

## Why this layout

The brief explicitly asks for *one file per topic so it's easy for development*. Each phase
is an isolated package; subteams can work in parallel without merge conflicts. The cascaded
pipeline imports the per-phase modules — it does not own their internals.
