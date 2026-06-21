# Vergabepilot.AI — Release Notes

## v0.2.0 — Global Coverage, Scale & Honest Reporting (June 2026)

A major evolution from the 5-strategy German-focused cascade into a globally-aware, scale-hardened system that fails honestly when it must.

### Highlights

**7-Strategy Cascade** — Two new strategies join the loop: **Adaptive** (`adaptive_universal`), a free country/language-agnostic heuristic scraper that runs before any paid LLM step, and **Learned Route** (`learned_route`), which replays a navigation route the CUA previously proved works — cheap Playwright, no LLM or vision. Full order: `EXISTING → DETERMINISTIC → ADAPTIVE → LLM_GENERATED → LEARNED_ROUTE → CUA → MANUAL`, with the last two injected automatically at the right point.

**URL Intelligence — 30 portal types across every continent** — A no-HTTP pre-classifier (`url_intelligence.py`) routes each URL to the cheapest viable strategy order: German/DTVP, EU (TED, UK, FR, PL, ES, PT, NL, BE, AT, CH, IT, IE, Nordics, Eastern Europe), Americas (US SAM, Canada, LATAM), Asia (India GeM + more), Africa, and Oceania (AusTender, NZ GETS). Auth-gated portals skip the LLM entirely.

**Built for 1,000+ URL jobs (designed to 10,000+)** — Chunked fan-out with per-domain **circuit breaker** and **rate limiter** (Redis), a **domain LLM dedup lock** + global semaphore, resilient HTTP retry/backoff with jitter, job resumability (skip already-succeeded items on retry), worker recycling, and hourly disk cleanup. structlog correlation IDs (`job:item`) thread the whole lifecycle.

**Honest Failure Reporting** — The ~27 fine-grained failure categories collapse into 8 plain-English **outcome buckets**; the two a human can fix (login required, CAPTCHA) surface in a **"Needs manual action"** queue (`GET /api/jobs/needs-manual`) with a suggested next step. `/api/admin/stats` returns the bucket breakdown.

**Public Tender Directory** — A read-only, per-IP rate-limited `/api/directory` (and `/directory` UI page) browses currently-open tenders grouped by portal, exposing only a whitelist of tender-facing fields. Backed by denormalized `JobItem` columns (`tender_title`, `tender_reference`, `deadline`) and a composite index.

**Auto-orchestration & multi-country pipeline** — The full pipeline auto-runs end to end; international URL detection works for any region; deterministic + adaptive paths keep most public portals free.

### New metrics & observability
HTTP retries, circuit-breaker events, and rate-limit hits are now exported at `/metrics`, alongside per-strategy scrape totals and durations.

### Migrations
`add_learned_route` (CUA route column) and `add_tender_directory_fields` (directory projection + index), applied automatically on startup.

### Tests
Backend suite grown to **225 tests** (URL intelligence, adaptive scraper, CUA route learner, directory, outcomes, HTTP client, rate limiter, logger context, global coverage).

---

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
