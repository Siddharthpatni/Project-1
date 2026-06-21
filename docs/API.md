# API Reference — Vergabepilot.AI

Base URL (local): `http://localhost:8000`
Interactive Swagger UI: **`/docs`** · OpenAPI JSON: **`/openapi.json`**

All routes are mounted under `/api/*` except the system probes (`/health`, `/ready`, `/metrics`, `/`). Responses are JSON unless noted. CORS allows the origins in `ALLOWED_ORIGINS`.

## Table of Contents
1. [System & Health](#1-system--health)
2. [Jobs](#2-jobs--apijobs)
3. [Scrapers](#3-scrapers--apiscrapers)
4. [Tender Directory (public)](#4-tender-directory--apidirectory)
5. [Admin](#5-admin--apiadmin)
6. [Audit](#6-audit--apiaudit)
7. [Extraction](#7-extraction--api)
8. [Evaluation (Phase 1)](#8-evaluation--apievaluation)
9. [Agents (Phase 2 CUA)](#9-agents--apiagents)
10. [Tests](#10-tests--apitests)

---

## 1. System & Health

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | Service banner — name, version, phases |
| `GET` | `/health` | Liveness — checks PostgreSQL. `{"status":"ok","database":"ok","version":"0.2.0"}` |
| `GET` | `/ready` | Readiness — checks PostgreSQL **and** Redis. `503` if any dependency is down |
| `GET` | `/metrics` | Prometheus text format (scrapes, durations, retries, breaker events, rate-limit hits) |

---

## 2. Jobs — `/api/jobs`

A **Job** is a batch of URLs; each URL is a **JobItem** processed independently through the cascade.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/jobs` | Create a job from a list of URLs |
| `POST` | `/api/jobs/upload` | Create a job from an uploaded CSV / Excel file |
| `POST` | `/api/jobs/smart-domain` | Create a job with one primary (+ optional backup) URL per domain |
| `GET` | `/api/jobs` | List recent jobs (`?limit=50`) |
| `GET` | `/api/jobs/{job_id}` | Full job detail with items + attempt chains |
| `GET` | `/api/jobs/needs-manual` | Items that need human action (auth/CAPTCHA) — `?limit`, `?job_id` |
| `GET` | `/api/jobs/local-files` | Documents available on the local disk fallback |
| `GET` | `/api/jobs/{job_id}/documents` | List documents for a job |
| `GET` | `/api/jobs/{job_id}/documents/{doc_id}/download` | Download one document |
| `GET` | `/api/jobs/{job_id}/documents-by-path/{item_id}/{filename}` | Download by path |
| `GET` | `/api/jobs/{job_id}/download-all` | Download all job documents as a ZIP |
| `GET` | `/api/jobs/{job_id}/error-report` | CSV error report (per-URL failure reasons) |
| `GET` | `/api/jobs/{job_id}/diagnostics` | Failures grouped by domain + error category |
| `POST` | `/api/jobs/{job_id}/items/{item_id}/retry` | Re-queue a single failed item |
| `POST` | `/api/jobs/{job_id}/stop` | Stop a running job |
| `DELETE` | `/api/jobs/{job_id}` | Delete a job and its items/documents |

### `POST /api/jobs`

```json
{
  "urls": ["https://www.dtvp.de/Satellite/notice/CXP4Y..."],
  "submitted_by": "ops-team",
  "force_strategy": null,
  "force_model": null
}
```

- `urls` — 1 to **500** URLs (validated `HttpUrl`). For larger batches use `POST /api/jobs/upload`.
- `force_strategy` *(optional)* — pin the cascade to one `Strategy` enum value (debugging): `existing_scraper`, `deterministic_template`, `adaptive_universal`, `llm_generated_scraper`, `learned_route`, `computer_use_agent`, `manual_scraper`.
- `force_model` *(optional)* — pin the LLM model.

**Response `201`:**
```json
{ "id": "f3c1...", "status": "pending", "total_urls": 1, "completed": 0, "cost_usd": 0.0 }
```
The job is enqueued to Celery; poll `GET /api/jobs/{id}` for progress.

### `POST /api/jobs/upload`
`multipart/form-data` with a `file` field (CSV or `.xlsx`). The first URL-like column is auto-detected. Handles large batches (1,000+ URLs), which are chunked (`JOB_CHUNK_SIZE`) and fanned out across workers.

### `POST /api/jobs/smart-domain`
```json
{
  "domain_urls": {
    "dtvp.de": ["https://primary...", "https://backup..."]
  },
  "submitted_by": "ops-team"
}
```
One primary URL per domain with an optional backup that is tried automatically if the primary fails. Returns a `SmartDomainBatchResult` with domain counts and `domains_with_backup`.

### `GET /api/jobs/needs-manual`
Items whose failure falls into a human-fixable outcome bucket (`auth_gated`, `captcha`). Each row includes the URL, domain, bucket, and a suggested action.

---

## 3. Scrapers — `/api/scrapers`

The registry of reusable scrapers (cached, LLM-generated, or manual), keyed by domain.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/scrapers` | List all `ScraperTemplate`s with health stats |
| `POST` | `/api/scrapers` | Manually register a scraper |
| `GET` | `/api/scrapers/{domain}` | Get the scraper for a domain |
| `GET` | `/api/scrapers/{scraper_id}/download` | Download the scraper's Python source |
| `DELETE` | `/api/scrapers/{scraper_id}` | Delete a scraper |
| `POST` | `/api/scrapers/learn` | Trigger CUA route learning for a URL |

Each template exposes `source` (`llm` / `manual` / `cua`), `platform`, `route_used`, `success_count`, `failure_count`, `avg_runtime`, and whether a `learned_route` / `cua_hint` exists.

---

## 4. Tender Directory — `/api/directory`

A **public, unauthenticated, per-IP rate-limited** (`PUBLIC_RATE_LIMIT_PER_MINUTE`, default 60/min) read-only view over successfully-scraped tenders. Only a whitelist of tender-facing fields is exposed — never internal errors, costs, or strategy traces. A tender is shown only when **published** (`status == success`) **and open** (deadline in the future or unknown).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/directory/domains` | Every known portal + live open-tender count (open-first) |
| `GET` | `/api/directory/domains/{domain}/tenders` | Paginated open tenders for a domain, soonest-closing first |

### `GET /api/directory/domains/{domain}/tenders?limit=20&offset=0`
```json
{
  "domain": "dtvp.de",
  "total": 42,
  "limit": 20,
  "offset": 0,
  "tenders": [
    {
      "job_id": "f3c1...",
      "item_id": "9a2b...",
      "title": "Lieferung von Büromöbeln",
      "reference": "VN-2026-0042",
      "deadline": "2026-07-15T00:00:00",
      "status": "closing_soon",
      "url": "https://www.dtvp.de/Satellite/notice/..."
    }
  ]
}
```
`status` is one of `open`, `closing_soon` (< 7 days), or `deadline_unknown`. The seed catalogue (`portal_directory_seed.py`) lists ~100 portals; any other scraped domain is surfaced too.

---

## 5. Admin — `/api/admin`

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/admin/stats` | Aggregate KPIs, strategy distribution, **outcome buckets**, needs-manual count |
| `GET` | `/api/admin/errors` | Recent failed items (`?limit=50`) |
| `GET` | `/api/admin/system-check` | DB / Redis / S3 connectivity snapshot |
| `GET` | `/api/admin/circuit-breakers` | All open/half-open domain circuits |
| `DELETE` | `/api/admin/circuit-breakers/{domain}` | Manually reset a domain's circuit |
| `GET` | `/api/admin/verified-urls` | Curated known-good test URLs |
| `GET` | `/api/admin/url-intelligence` | Classify a single URL (`?url=`) — type, success rate, strategy order |
| `POST` | `/api/admin/url-intelligence/batch` | Pre-classify up to 50,000 URLs — type breakdown + forecast success |
| `POST` | `/api/admin/reset` | Reset aggregate counters |
| `POST` | `/api/admin/reset-stale-jobs` | Rescue jobs stuck in running/pending |

### `GET /api/admin/stats` (excerpt)
```json
{
  "jobs": 128,
  "items": 5021,
  "failed_items": 1402,
  "item_success_rate": 0.721,
  "total_cost_usd": 0.0431,
  "strategy_distribution": { "deterministic_template": 1903, "llm_generated_scraper": 1110 },
  "outcome_buckets": { "success": 3619, "auth_gated": 540, "captcha": 88, "unreachable": 410 },
  "outcome_bucket_labels": { "auth_gated": "Login / registration required" },
  "needs_manual_count": 628
}
```

---

## 6. Audit — `/api/audit`

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/audit` | Append-only event stream (`?level=`, `?event_type=`, `?limit=`) |
| `GET` | `/api/audit/jobs/{job_id}` | All audit events for one job |
| `GET` | `/api/audit/stats` | Event counts by level / type |
| `DELETE` | `/api/audit` | Purge audit log (admin only) |

---

## 7. Extraction — `/api`

Deep field extraction over downloaded documents (mounted at `/api`).

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/extraction` | List extraction records (`?limit=`) |
| `GET` | `/api/extraction/{job_item_id}` | Extracted fields for one item |
| `GET` | `/api/extraction/{job_item_id}/report` | Generate a PDF/DOCX report (`?format=pdf|docx`) |
| `POST` | `/api/extraction/{job_item_id}/trigger` | Re-run extraction for one item |
| `POST` | `/api/extraction/job/{job_id}` | Run extraction across a whole job (async) |
| `GET` | `/api/extraction/task/{task_id}` | Poll an async extraction task |

Extraction runs automatically after every successful download; these endpoints re-run or fetch results on demand. See [TENDER_EXTRACTOR.md](TENDER_EXTRACTOR.md) for the 22 fields and parsers.

---

## 8. Evaluation — `/api/evaluation`

Phase-1 benchmarking + pipeline analytics.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/evaluation/run` | Launch a benchmark (model × URLs) — `202 Accepted` |
| `GET` | `/api/evaluation/runs` | List benchmark rows |
| `GET` | `/api/evaluation/summary` | Per-model success rate / cost / latency |
| `GET` | `/api/evaluation/pipeline` | Pipeline-level analytics (strategy mix, throughput) |
| `GET` | `/api/evaluation/scraper-health` | Registry health — which scrapers are winning/retiring |

---

## 9. Agents — `/api/agents`

Phase-2 Computer-Use-Agent (CUA) sessions.

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/agents/run` | Launch a CUA session against a URL — `202 Accepted` |
| `GET` | `/api/agents/runs` | List agent runs with traces |
| `GET` | `/api/agents/summary` | Agent leaderboard — success rate, steps, cost |

---

## 10. Tests — `/api/tests`

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/tests/run` | Run the backend pytest suite from the UI and stream results |

---

## Errors

Unhandled exceptions return `{"detail": "Internal server error"}` with status `500` (details are written to the audit log, never leaked to the client). Validation errors return FastAPI's standard `422` body. SSRF/injection-blocked URLs fail the item with a `blocked` outcome and a `CRITICAL` audit event.
