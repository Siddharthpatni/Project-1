# Vergabepilot.AI — Release Notes

## v0.1.0 — Agentic Cascade Pipeline (May 2026)

First production-ready release of Vergabepilot.AI, an autonomous agentic system for scraping and downloading public procurement (tender) documents across fragmented German and EU portals.

### Highlights

**Agentic Cascade Scraper Loop** — A fail-safe pipeline that routes each notice URL through escalating strategies, prioritizing speed and cost-efficiency before resorting to expensive agents: manual scripts -> cached/existing scrapers -> deterministic DTVP/Satellite URL builders -> LLM-synthesized Playwright scrapers -> visual Computer-Use Agents.

**Phase 1 — LLM Scraper Generation & Sandbox** — Generative LLMs read a portal's structure, synthesize custom Playwright code, validate it inside a sandboxed environment, and iteratively self-heal based on stdout/stderr logs. Includes automatic self-healing for moderate-risk errors and high-risk terminal sandbox blocks.

**Phase 2 — Visual Computer-Use Agents (CUA)** — Visual browser-automation agents (unified on `browser-use`) interact with portals via screenshots, mouse coordinates, and keyboard input to get past anti-scraping paywalls. Adds CUA pre-flight route discovery, stealth browser profiles, and human-interaction emulation.

**Deterministic Platform Templates** — Instant download-URL construction for DTVP/Satellite notice systems, with no browser overhead or LLM cost. The deterministic strategy is prioritized first in the cascade to pull full ZIP packages and avoid false-positive notice-PDF downloads.

**Global HTML Filtering & Safe-Saves** — Only genuine tender documents (PDF, ZIP, Word) are persisted; false-positive HTML downloads are filtered at the pipeline level.

**Real-time Admin Monitor & Security Diagnostics** — Centralized ops cockpit with pipeline metrics, strategy distribution, and live security diagnostics (prompt-injection checks, SSRF/sandbox-violation detection), plus a Stuck Jobs Recovery panel that auto-cleans zombie tasks on startup.

**Excel Workspace** — In-browser spreadsheet viewer with persistence migrated to native IndexedDB (resolving the localStorage 5MB quota limit), a connection singleton, and a 300ms save debounce to eliminate UI lag.

### Supported LLM Models (via OpenRouter routing schema)

- Google Gemini 2.5 Flash Lite / Flash / Pro
- Anthropic Claude 3.5 Sonnet / Haiku
- OpenAI GPT-4o / GPT-4o Mini

### Tech Stack

- **Backend:** Python, FastAPI, Uvicorn, Pydantic, Celery, Redis, SQLAlchemy + Alembic, PostgreSQL (psycopg 3), Playwright, BeautifulSoup4, lxml, browser-use, LangChain, OpenAI/Anthropic SDKs via OpenRouter, boto3 + MinIO, pandas/openpyxl, structlog, tenacity, pytest.
- **Frontend:** Next.js 14 (App Router), React 18, TypeScript, Tailwind CSS, SWR, Recharts, lucide-react, xlsx.
- **Infrastructure:** Docker & Docker Compose orchestrating PostgreSQL 16, Redis 7, MinIO, FastAPI gateway, Celery worker, and the Next.js UI.

### Notable Fixes

- Resolved Pydantic config bug and `BrowserProfile` validation errors.
- Locked stable `browser-use` 0.12.7 and resolved LangChain structured-schema validation errors on OpenRouter.
- Escaped f-string braces to fix a Celery worker crash.
- Fixed CI/CD docker build cache-key checksum error.

### Access Points

- Web Dashboard: http://localhost:3000
- FastAPI Docs (Swagger): http://localhost:8000/docs
- MinIO Console: http://localhost:9001
