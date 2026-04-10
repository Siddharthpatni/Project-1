# Phase 3 — Integrated System

**Goal:** Combine all approaches into a unified, deployed service.

## Files

| File | Responsibility |
|---|---|
| `pipeline.py` | The cascaded `process_url` function — the main entry point |
| `scraper_registry.py` | CRUD + statistics for reusable scrapers (keyed by domain) |
| `fallback.py` | Pure decision logic: which strategy to try next |
| `versioning.py` | Document checksum diffing for periodic re-checks |

## Cascade

```
            ┌──────────────────┐
            │ POST /api/jobs   │
            └────────┬─────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │ existing scraper       │── success ──▶ store + done
        │ (registry by domain)   │
        └────────┬───────────────┘
                 │ fail
                 ▼
        ┌────────────────────────┐
        │ LLM-generated scraper  │── success ──▶ promote to registry
        │ (Phase 1 feedback loop)│              + store + done
        └────────┬───────────────┘
                 │ fail
                 ▼
        ┌────────────────────────┐
        │ CUA fallback           │── success ──▶ store + done
        │ (Phase 2)              │
        └────────┬───────────────┘
                 │ fail
                 ▼
            error report
```

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
