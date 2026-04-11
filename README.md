# Vergabepilot.AI

**Agentic AI for Automated Public Project Scraping**
SoSe 2026 — European AI Team Projects (ATP) · CORE Research Group · in cooperation with Ciconia Systems GmbH

A production-ready, modular system that takes URLs of German/EU public tender websites as input and returns all relevant tender documents. Combines three complementary approaches behind a single REST API:

1. **Phase 1 — LLM-based Scraper Generation**: Generate Python/Playwright scraper code at runtime with an LLM, execute it in a sandbox, and iterate via a feedback loop.
2. **Phase 2 — Computer-Use Agents (CUA)**: GUI-based agents that interact with websites via a screenshot → action → new-state loop. Used when structured scraping fails.
3. **Phase 3 — Integrated System**: Cascaded pipeline (existing scraper → LLM-generated scraper → CUA fallback) exposed as an async REST service, deployed via Docker Compose.

## Repository layout

```
vergabepilot-ai/
├── backend/                      FastAPI + Celery + Playwright
│   └── app/
│       ├── api/                  REST routes (one file per resource)
│       ├── phase1_llm_scraper/   Phase 1: LLM scraper generation
│       ├── phase2_cua/           Phase 2: computer-use agents
│       ├── phase3_integration/   Phase 3: cascaded pipeline
│       ├── core/                 LLM client, storage, sandbox, security
│       ├── workers/              Celery tasks
│       └── utils/                Logging & metrics
├── frontend/                     Next.js 14 (App Router) + Tailwind
│   ├── app/                      One route per feature area
│   ├── components/               Reusable UI
│   └── lib/                      API client
├── docs/                         Architecture & per-phase docs
├── data/samples/                 Sample evaluation dataset
├── scripts/                      Dev helper scripts
└── docker-compose.yml            Full stack (api, worker, redis, postgres, minio, frontend)
```

Every phase is self-contained: each topic lives in its own file, so teams can work in parallel without conflicts.

## Quick start

```bash
cp .env.example .env
# fill in OPENROUTER_API_KEY
docker compose up --build
```

- Frontend:  http://localhost:3000
- API docs:  http://localhost:8000/docs
- MinIO:     http://localhost:9001  (minioadmin / minioadmin)

## Phases at a glance

| Phase | Entry point | Description |
|-------|-------------|-------------|
| 1 | `backend/app/phase1_llm_scraper/feedback_loop.py` | LLM generates scraper → execute sandboxed → evaluate → retry |
| 2 | `backend/app/phase2_cua/orchestrator.py`          | Screenshot-based agent loop using Playwright + LLM vision |
| 3 | `backend/app/phase3_integration/pipeline.py`      | Cascaded strategy with automatic fallback and error reporting |

See `docs/ARCHITECTURE.md` for the high-level picture, `docs/CONNECTIONS.md` for detailed internal connections, `docs/apis.md` for low-cost LLM selection, and `docs/PHASE{1,2,3}.md` for logic details.

## Grading alignment

Per the project brief: 50% code artifacts + documented evaluation, 50% presentations. This repo provides:

- A runnable Python library (`backend/app/phase1_llm_scraper`, `phase2_cua`, `phase3_integration`)
- An annotated evaluation harness (`backend/app/phase1_llm_scraper/evaluator.py`)
- REST API + async workers + object storage + containerized deployment
- Safety guardrails (sandboxed execution, code validation, prompt-injection protection)
- A client-facing web UI for submitting URLs and reviewing results

## License

Coursework — © 2026 TU Clausthal / Ostfalia / UBB Cluj in cooperation with Ciconia Systems GmbH.
