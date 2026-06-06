# API Reference — Vergabepilot.AI

**Base URL:** `http://localhost:8000`  
**Interactive docs:** `http://localhost:8000/docs` (Swagger UI)  
**OpenAPI schema:** `http://localhost:8000/openapi.json`

All API routes are prefixed with `/api/`. The Next.js frontend proxies them at `/api/backend/*`.

---

## Table of Contents
1. [Jobs](#1-jobs)
2. [Documents](#2-documents)
3. [Extraction](#3-extraction)
4. [Scrapers](#4-scrapers)
5. [Admin](#5-admin)
6. [Audit Log](#6-audit-log)
7. [Evaluation](#7-evaluation)
8. [Agents](#8-agents)
9. [System](#9-system)

---

## 1. Jobs

### POST `/api/jobs` — Create Job
Submit a list of URLs for processing through the cascade pipeline.

**Request body:**
```json
{
  "urls": ["https://www.dtvp.de/Satellite/...", "https://..."],
  "submitted_by": "optional-user-name",
  "force_strategy": "llm_generated_scraper",
  "force_model": "google/gemini-2.5-flash-lite"
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `urls` | `string[]` | Yes | 1–10,000 procurement notice URLs |
| `submitted_by` | `string` | No | Label for tracking (email, username) |
| `force_strategy` | `string` | No | Skip cascade, use one strategy only |
| `force_model` | `string` | No | Override LLM model for this job |

**Response `201`:**
```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "status": "pending",
  "total_urls": 12,
  "completed": 0,
  "cost_usd": 0.0,
  "created_at": "2026-06-06T12:00:00"
}
```

**`force_strategy` values:**

| Value | Stage |
|---|---|
| `existing_scraper` | Cached scraper only |
| `deterministic_template` | Deterministic download only |
| `llm_generated_scraper` | LLM generation only |
| `computer_use_agent` | CUA agent only |
| `manual_scraper` | Manual Phase 0 only |

---

### POST `/api/jobs/upload` — Create Job from File
Upload a CSV or XLSX file containing URLs (auto-detects URL column).

**Request:** `multipart/form-data`  
**Fields:** `file` (`.csv` / `.xlsx` / `.xls`)  
**Query params:** `force_strategy`, `force_model`, `submitted_by`

**Response `201`:** Same as POST `/api/jobs`

---

### GET `/api/jobs` — List Jobs

**Query params:**

| Param | Default | Description |
|---|---|---|
| `limit` | 50 | Max jobs to return |

**Response `200`:**
```json
[
  {
    "id": "...",
    "status": "running",
    "total_urls": 100,
    "completed": 47,
    "cost_usd": 0.0043,
    "created_at": "...",
    "domains": ["dtvp.de", "evergabe-online.de"],
    "items": [...]
  }
]
```

---

### GET `/api/jobs/{job_id}` — Get Job Detail

Returns the full job with all items, strategies, attempt chains, and document counts.

**Response `200`:**
```json
{
  "id": "...",
  "status": "partial",
  "total_urls": 10,
  "completed": 9,
  "cost_usd": 0.0012,
  "items": [
    {
      "id": "...",
      "url": "https://...",
      "domain": "dtvp.de",
      "status": "success",
      "strategy": "deterministic_template",
      "iterations": 1,
      "runtime_seconds": 3.4,
      "failure_category": null,
      "attempts_detail": [
        {
          "strategy": "existing_scraper",
          "success": false,
          "downloaded": 0,
          "duration_s": 0.8,
          "timestamp": "2026-06-06T12:00:01",
          "error_raw": "no cached scraper found",
          "error_category": "no_strategy",
          "error_reason": "No Strategy"
        },
        {
          "strategy": "deterministic_template",
          "success": true,
          "downloaded": 2,
          "duration_s": 3.4,
          "timestamp": "2026-06-06T12:00:02"
        }
      ],
      "document_count": 2
    }
  ]
}
```

---

### POST `/api/jobs/{job_id}/items/{item_id}/retry` — Retry Item

Re-runs the cascade pipeline for a single failed item.

**Response `202`:** `{ "queued": true, "item_id": "..." }`

---

### POST `/api/jobs/{job_id}/stop` — Stop Job

Marks all pending/running items as failed and stops processing.

**Response `200`:** `{ "stopped": 8 }`

---

### DELETE `/api/jobs/{job_id}` — Delete Job

Deletes the job, all items, and all stored documents from MinIO.

**Response `204`:** No content

---

### GET `/api/jobs/{job_id}/download-all` — Download ZIP

Returns all documents for a job bundled into a single ZIP file.

**Response `200`:** `application/zip`  
**Content-Disposition:** `attachment; filename="job-{id[:8]}-docs.zip"`

---

### GET `/api/jobs/{job_id}/diagnostics` — Job Diagnostics

Returns a failure breakdown grouped by domain, error category, and strategy.

**Response `200`:**
```json
{
  "job_id": "...",
  "succeeded": 45,
  "failed": 5,
  "pending": 0,
  "cost_usd": "0.0043",
  "error_category_breakdown": {
    "timeout": 2,
    "login_required": 3
  },
  "domain_results": {
    "dtvp.de": {
      "urls": [
        { "url": "...", "status": "success", "strategy": "deterministic_template" },
        { "url": "...", "status": "failed", "error": "timeout after 45s" }
      ]
    }
  },
  "audit_trail": [...]
}
```

---

### GET `/api/jobs/{job_id}/error-report` — Error Report

**Query params:** `fmt=json` (default) or `fmt=csv`

Returns all failed items with error details for offline analysis.

---

## 2. Documents

### GET `/api/jobs/{job_id}/documents` — List Documents

Returns all downloaded documents for a job with download URLs.

**Response `200`:**
```json
[
  {
    "id": "...",
    "job_item_id": "...",
    "filename": "Leistungsverzeichnis.pdf",
    "mime_type": "application/pdf",
    "size_bytes": 204800,
    "version": 1,
    "checksum": "sha256:abc...",
    "created_at": "...",
    "download_url": "/jobs/{job_id}/documents/{doc_id}/download"
  }
]
```

---

### GET `/api/jobs/{job_id}/documents/{doc_id}/download` — Download Document

Streams the document from MinIO.

**Response `200`:** Document bytes with correct `Content-Type` and `Content-Disposition`.

---

## 3. Extraction

Deep field extraction from downloaded procurement documents.

### GET `/api/extract` — List Extraction Records

**Query params:** `limit` (1–500, default 100)

---

### GET `/api/extract/{job_item_id}` — Get Extracted Fields

Returns structured fields extracted from documents for a specific job item.

**Response `200`:**
```json
{
  "id": "...",
  "job_item_id": "...",
  "source_url": "https://...",
  "docs_parsed": 3,
  "runtime_seconds": 4.2,
  "created_at": "...",
  "fields": {
    "vergabenummer": "VN-2026-0042",
    "titel": "Lieferung von Büromöbeln",
    "auftraggeber": "Bundesministerium der Finanzen",
    "abgabefrist": "15.07.2026",
    "auftragswert": "500000",
    "waehrung": "EUR",
    "cpv_codes": ["39130000"],
    "nuts_codes": ["DE30"],
    "email": "vergabe@bmf.bund.de",
    "zuschlagskriterien": ["Preis 60%", "Qualität 40%"]
  }
}
```

---

### POST `/api/extract/{job_item_id}/trigger` — Re-run Extraction

Re-runs both regex extraction and LLM enhancement for a job item.

**Response `200`:** Full extraction result (same schema as GET above)

---

### POST `/api/extract/job/{job_id}` — Bulk Extract Job

Triggers extraction for all items in a job. Uses S3-stored documents when available, falls back to live fetch when documents are missing.

**Response `200`:**
```json
{
  "job_id": "...",
  "extracted": 9,
  "failed": 1,
  "live_fetched": 0,
  "results": [...]
}
```

---

### GET `/api/extract/{job_item_id}/report` — Download Extraction Report

**Query params:** `fmt=pdf` (default) or `fmt=docx`

Generates a branded report with all extracted fields and document text excerpts.

**Response `200`:** `application/pdf` or `application/vnd.openxmlformats-officedocument.wordprocessingml.document`

---

## 4. Scrapers

### GET `/api/scrapers` — List Scrapers

Returns all saved scrapers in the registry with performance stats.

**Response `200`:**
```json
[
  {
    "id": "...",
    "domain": "dtvp.de",
    "source": "llm",
    "platform": "dtvp",
    "route_used": false,
    "success_count": 142,
    "failure_count": 3,
    "avg_runtime": 8.4,
    "cua_hint": "...",
    "code": "import asyncio\n...",
    "created_at": "...",
    "updated_at": "..."
  }
]
```

---

### POST `/api/scrapers/learn` — Learn Route + Generate Scraper

Triggers route learning: navigates the portal with a CUA agent, records click interactions, then generates a scraper from the trace.

**Request body:**
```json
{
  "url": "https://www.evergabe-online.de/...",
  "model": "google/gemini-2.5-flash-lite"
}
```

**Response `200`:**
```json
{
  "domain": "evergabe-online.de",
  "status": "generated_and_saved",
  "documents_found": 3,
  "scraper_code": "import asyncio\n...",
  "route_map": {
    "steps": [
      { "action": "click", "selector": "#download-btn", "description": "Click Download All" }
    ]
  },
  "cost_usd": 0.0003
}
```

---

### DELETE `/api/scrapers/{scraper_id}` — Delete Scraper

Removes a scraper from the registry. Next run for this domain will regenerate it.

**Response `204`:** No content

---

## 5. Admin

### GET `/api/admin/stats` — System Statistics

Returns aggregate pipeline metrics for the dashboard.

**Response `200`:**
```json
{
  "jobs": 124,
  "items": 8420,
  "succeeded": 7890,
  "failed": 530,
  "pending": 0,
  "total_cost_usd": 0.84,
  "item_success_rate": 0.937,
  "scraper_templates": 47,
  "strategy_distribution": {
    "existing_scraper": 4200,
    "deterministic_template": 1800,
    "llm_generated_scraper": 1200,
    "computer_use_agent": 320,
    "manual_scraper": 370,
    "none": 530
  },
  "strategy_success_distribution": {
    "existing_scraper": 4100,
    "deterministic_template": 1780,
    "llm_generated_scraper": 1050,
    "computer_use_agent": 280,
    "manual_scraper": 350
  },
  "error_categories": { "timeout": 120, "login_required": 80 }
}
```

---

### GET `/api/admin/errors` — Failed Items

Returns recently failed job items with error details.

---

### POST `/api/admin/reset` — Reset All Data

**Dangerous:** Clears all jobs, documents, and scrapers. Requires `{ "confirm": "reset" }` in body.

---

### POST `/api/admin/reset-stale-jobs` — Rescue Stale Jobs

Marks any jobs stuck in `running`/`pending` for > 2 hours as `failed`. Also run automatically on startup and by Celery Beat every 5 minutes.

---

### GET `/api/admin/system-check` — System Integrity Check

Returns connectivity status for all backend dependencies (PostgreSQL, Redis, MinIO).

---

## 6. Audit Log

### GET `/api/audit` — List Audit Events

**Query params:**

| Param | Description |
|---|---|
| `limit` | Max events (default 200) |
| `level` | Filter by `info`, `warning`, `error`, `critical` |
| `job_id` | Filter by specific job |
| `event_type` | Filter by event type string |

**Response `200`:**
```json
[
  {
    "id": "...",
    "created_at": "2026-06-06T12:00:00",
    "level": "error",
    "event_type": "strategy.failure",
    "job_id": "...",
    "domain": "vergabe-portal.de",
    "url": "https://...",
    "strategy": "llm_generated_scraper",
    "message": "Sandbox timeout after 45s",
    "extra": { "error_category": "timeout", "iteration": 2 }
  }
]
```

---

### GET `/api/audit/stats` — Audit Statistics

Returns event counts grouped by level.

**Response `200`:**
```json
{
  "total": 42800,
  "by_level": {
    "info": 40000,
    "warning": 2400,
    "error": 350,
    "critical": 50
  }
}
```

---

### DELETE `/api/audit` — Clear Audit Log

Deletes all audit log entries. Use with caution — irreversible.

---

## 7. Evaluation

Phase 1 LLM benchmarking — measures how well each model generates working scrapers.

### GET `/api/evaluation` — List Evaluation Runs

### POST `/api/evaluation/run` — Run Benchmark

**Request body:**
```json
{
  "model": "google/gemini-2.5-flash-lite",
  "urls": ["https://..."],
  "expected_docs": 3
}
```

### GET `/api/evaluation/summary` — Aggregated Results

Returns success rate, avg cost, avg runtime per model.

---

## 8. Agents

Phase 2 CUA agent benchmarking.

### GET `/api/agents/summary` — Agent Performance Summary

Returns per-engine statistics (runs, accuracy, avg steps, cost).

### GET `/api/agents/runs` — List Agent Runs

Returns all CUA session records with traces and downloaded file lists.

### POST `/api/agents/run` — Trigger CUA Session

**Request body:**
```json
{
  "agent_name": "playwright_cua",
  "url": "https://www.evergabe-online.de/...",
  "model_name": "google/gemini-2.5-flash-lite"
}
```

---

## 9. System

### GET `/health` — Liveness Check

```json
{ "status": "ok", "database": "ok", "version": "0.2.0" }
```

HTTP `200` = alive. HTTP `503` = database unreachable.

---

### GET `/ready` — Readiness Check

```json
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok"
  }
}
```

HTTP `200` = ready to receive traffic. HTTP `503` = not ready (use for load balancer health checks).

---

### GET `/metrics` — Prometheus Metrics

Returns Prometheus text format. Mount at your Prometheus scrape target.

---

### GET `/` — Service Info

```json
{
  "service": "vergabepilot.ai",
  "version": "0.2.0",
  "phases": ["phase1_llm_scraper", "phase2_cua", "phase3_integration"],
  "docs": "/docs"
}
```

---

## Error Responses

All error responses follow the same format:

```json
{
  "detail": "Human-readable error message"
}
```

| HTTP Code | Meaning |
|---|---|
| `400` | Bad request — missing or invalid fields |
| `404` | Resource not found |
| `422` | Validation error — request body doesn't match schema |
| `500` | Internal server error (detail intentionally vague — see audit log) |
