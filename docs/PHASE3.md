# Phase 3 — Integrated System

**Goal:** Combine all approaches into a unified, deployed service.

> This is the original Phase-3 brief. The integrated system has since grown from
> a 3-strategy cascade into a **7-strategy** one with a URL-intelligence layer,
> honest outcome buckets, and a public tender directory. See
> [PIPELINE.md](PIPELINE.md) and [ARCHITECTURE.md](ARCHITECTURE.md) for the
> current design; this file is kept for historical context.

## Files

| File | Responsibility |
|---|---|
| `pipeline.py` | The cascaded `process_url` function — the main entry point |
| `url_intelligence.py` | Pre-classify URLs (30 portal types) + circuit breaker + rate limiter |
| `adaptive_scraper.py` | Strategy 3 — free, country/language-agnostic heuristic scraper |
| `deterministic.py` | Strategy 2 — direct ZIP download for DTVP/Satellite/NetServer |
| `scraper_registry.py` | CRUD + statistics for reusable scrapers + learned routes (keyed by domain) |
| `platform_classifier.py` | URL/HTML portal fingerprinting + deterministic URL builders |
| `outcomes.py` | Collapse 27 failure categories → 8 honest buckets + needs-manual logic |
| `portal_directory_seed.py` | ~100 seed portal domains for the public directory |
| `fallback.py` | Pure decision logic: which strategy to try next |
| `versioning.py` | Document checksum diffing for periodic re-checks |

## Cascade (current — 7 strategies)

```
POST /api/jobs
      │
      ▼
URL intelligence ── classify type · circuit breaker · rate limiter
      │  selects a strategy order tuned to the portal type
      ▼
1 existing ─▶ 2 deterministic ─▶ 3 adaptive ─▶ 4 LLM-generated
      ─▶ 5 learned route ─▶ 6 CUA ─▶ 7 manual
      │ (first to return documents wins; the rest are skipped)
      ▼
success: store + deep-extract   |   failure: classify into outcome bucket
```

`ADAPTIVE` is injected before the paid LLM step and `LEARNED_ROUTE` before CUA.
The `next_strategy` function in `fallback.py` is intentionally pure and
side-effect-free so it's trivially unit-testable. See `tests/test_phase3.py`.

## REST API surface

| Verb | Path | Purpose |
|------|------|---------|
| POST | `/api/jobs` | Submit a list of URLs |
| GET  | `/api/jobs` | List jobs |
| GET  | `/api/jobs/{id}` | Job detail (items, status) |
| GET  | `/api/jobs/{id}/documents` | All downloaded documents |
| GET  | `/api/scrapers` | List registry templates |
| POST | `/api/scrapers` | Add a manually-written scraper |
| POST | `/api/evaluation/run` | Trigger a Phase 1 benchmark |
| GET  | `/api/evaluation/summary` | Per-model aggregates |
| POST | `/api/agents/run` | Trigger a single CUA run |
| GET  | `/api/agents/summary` | Per-agent aggregates |
| GET  | `/api/admin/stats` | Global counters |
| GET  | `/api/admin/errors` | Recent failed items |

## Deployment

`docker compose up --build` brings up six services: api, worker, beat, redis,
postgres, minio, frontend. Tested on Docker 24+.

### Production hardening checklist

- [ ] Replace MinIO with managed S3 + IAM role
- [ ] Replace `SECRET_KEY` and DB credentials with values from a secrets manager
- [ ] Set `ALLOWED_ORIGINS` to your real frontend domain
- [ ] Run worker container under gVisor / Firecracker
- [ ] Add rate limiting on `/api/jobs` (e.g. via slowapi or an API gateway)
- [ ] Wire `app.utils.metrics` to Prometheus
- [ ] Add Sentry for error reporting
- [ ] Periodic backup of the postgres volume

## Hidden-dataset evaluation

Per the project brief, the final phase-3 service will be tested with a hidden
dataset for robustness, document download success rate, runtime, and API cost.
The evaluation harness in `phase1_llm_scraper/evaluator.py` is the same one you
should plug the hidden dataset into.
