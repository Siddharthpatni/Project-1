# Deployment Guide — Vergabepilot.AI

## Table of Contents
1. [Local Development](#1-local-development)
2. [Environment Variables](#2-environment-variables)
3. [Docker Compose Stack](#3-docker-compose-stack)
4. [Scaling Workers](#4-scaling-workers)
5. [Production Checklist](#5-production-checklist)
6. [Database Migrations](#6-database-migrations)
7. [Monitoring](#7-monitoring)
8. [Troubleshooting](#8-troubleshooting)

---

## 1. Local Development

### Prerequisites

| Tool | Minimum Version |
|---|---|
| Docker Desktop | 4.x |
| RAM allocated to Docker | 8 GB (16 GB for CUA) |
| Disk space | 10 GB |

### Setup

```bash
# 1. Clone
git clone https://github.com/Siddharthpatni/Vergabepilot-v1.git
cd Vergabepilot-v1

# 2. Configure environment
cp .env.example .env
# Edit .env — fill in all REQUIRED values (see section 2)

# 3. Build images
docker compose build

# 4. Start everything
docker compose up -d

# 5. Verify health
docker compose ps
curl localhost:8000/health
curl localhost:8000/ready
```

**Dashboard:** `http://localhost:3000`  
**API docs:** `http://localhost:8000/docs`  
**MinIO console:** `http://localhost:9001`

---

## 2. Environment Variables

Copy `.env.example` to `.env` and fill in all values. Never commit `.env` to version control.

### Required (app will not start without these)

| Variable | Description | Generate with |
|---|---|---|
| `SECRET_KEY` | JWT / session signing key (min 32 chars) | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `POSTGRES_USER` | PostgreSQL username | Any string, e.g. `vergabepilot` |
| `POSTGRES_PASSWORD` | PostgreSQL password (strong) | Use a password manager |
| `MINIO_ROOT_USER` | MinIO access key (min 8 chars) | Any string, not `minioadmin` |
| `MINIO_ROOT_PASSWORD` | MinIO secret key (min 12 chars) | Use a password manager |

### LLM Provider

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Get free key at [openrouter.ai](https://openrouter.ai) |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Override for self-hosted |
| `LLM_MODEL_PRIMARY` | `google/gemini-2.5-flash-lite` | Primary LLM for scraper generation |
| `LLM_MODEL_FALLBACK` | `google/gemini-2.5-flash-lite` | Fallback if primary fails |
| `LLM_MODEL_VISION` | `google/gemini-2.5-flash-lite` | Vision model for CUA screenshots |

### Performance Tuning

| Variable | Default | Description |
|---|---|---|
| `JOB_CONCURRENCY` | `8` | Parallel URLs processed per chunk task (asyncio) |
| `JOB_CHUNK_SIZE` | `50` | URLs per Celery chunk task |
| `LLM_GLOBAL_CONCURRENCY` | `8` (compose) / `2` (code default) | Max simultaneous LLM API calls per worker |
| `DOMAIN_LLM_LOCK_TTL` | `360` | Seconds to hold the per-domain Redis dedup lock |
| `SANDBOX_TIMEOUT_SECONDS` | `45` | Max sandbox execution time |
| `SANDBOX_MEMORY_MB` | `512` | Sandbox memory ceiling |

### Cascade Feature Flags

These are read by the **workers** (which run the pipeline), so set them in the worker environment.

| Variable | Default | Description |
|---|---|---|
| `ENABLE_FALLBACK_CUA` | `true` | Allow the CUA (Strategy 6) in the cascade |
| `ENABLE_CUA_ROUTE_LEARNING` | `true` | Learn a replayable route after a CUA-only success (powers Strategy 5) |
| `ENABLE_ROUTE_LEARNING` | `false` | Pre-trace the click path before LLM generation (adds 20–30 s/URL) |

### Security

| Variable | Default | Description |
|---|---|---|
| `VERGABEPILOT_ENV` | `development` | Set to `production` for hard-fail on insecure defaults |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | CORS allowed origins (comma-separated) |
| `PUBLIC_RATE_LIMIT_PER_MINUTE` | `60` | Per-IP cap on the public tender directory |

---

## 3. Docker Compose Stack

### Service Overview

```
docker compose ps

NAME                          IMAGE                      STATUS
vergabepilot-ai-api-1         vergabepilot-ai-api        Up (healthy)  :8000
vergabepilot-ai-frontend-1    vergabepilot-ai-frontend   Up            :3000
vergabepilot-ai-postgres-1    postgres:16-alpine         Up (healthy)  :5432
vergabepilot-ai-redis-1       redis:7-alpine             Up (healthy)  :6379
vergabepilot-ai-minio-1       minio/minio:latest         Up (healthy)  :9000/:9001
vergabepilot-ai-worker-default-1  vergabepilot-ai-api   Up
vergabepilot-ai-worker-chunks-1   vergabepilot-ai-api   Up
vergabepilot-ai-worker-chunks-2   vergabepilot-ai-api   Up
vergabepilot-ai-worker-cua-1      vergabepilot-ai-api   Up
vergabepilot-ai-beat-1            vergabepilot-ai-api   Up
```

### Useful Commands

```bash
# View live logs
docker compose logs -f api
docker compose logs -f worker-chunks

# Restart a single service
docker compose restart api

# Stop everything
docker compose down

# Stop and wipe all data (destructive!)
docker compose down -v

# Rebuild after code changes
docker compose build api frontend
docker compose up -d api frontend
```

---

## 4. Scaling Workers

The `worker-chunks` pool is the main throughput bottleneck. Concurrent URLs = `replicas × Celery concurrency (2) × JOB_CONCURRENCY (8)`.

```bash
# Default: 2 replicas × 2 × 8 = ~32 concurrent URLs
docker compose up --scale worker-chunks=2 -d

# ~2× throughput: 4 replicas → ~64 concurrent URLs
docker compose up --scale worker-chunks=4 -d

# ~4× throughput: 8 replicas → ~128 concurrent URLs
docker compose up --scale worker-chunks=8 -d
```

Jobs of any size still work at the default scale — a 10,000-URL job is split into chunks of `JOB_CHUNK_SIZE` and streamed through the fixed worker pool; chunk tasks skip already-`SUCCESS` items on retry (resumability).

**Memory per replica:** ~512 MB base + up to 512 MB per sandbox execution.

**Rule of thumb:** 1 GB RAM per `worker-chunks` replica when using LLM generation heavily.

### Tuning `JOB_CONCURRENCY`

`JOB_CONCURRENCY` controls the asyncio concurrency within each chunk task (how many URLs it processes in parallel inside one Celery task).

| Setting | Best for |
|---|---|
| `4` | Heavy browser/CUA-bound workloads |
| `8` (default) | Mixed workload |
| `16–32` | Mostly deterministic/cached (low browser usage) |

---

## 5. Production Checklist

Before deploying to a public server:

### Security

- [ ] `VERGABEPILOT_ENV=production` in `.env` (triggers hard-fail on weak secrets)
- [ ] `SECRET_KEY` is 64+ hex chars, not `change-me`
- [ ] `POSTGRES_PASSWORD` is 20+ chars, not `vergabepilot`
- [ ] `MINIO_ROOT_PASSWORD` is 16+ chars, not `minioadmin`
- [ ] `ALLOWED_ORIGINS` is set to your actual frontend domain
- [ ] MinIO console port `:9001` is NOT exposed publicly
- [ ] PostgreSQL port `:5432` is NOT exposed publicly (only API needs it)
- [ ] Redis port `:6379` is NOT exposed publicly

### Infrastructure

- [ ] HTTPS configured (reverse proxy: nginx / Caddy / Traefik)
- [ ] `/health` and `/ready` endpoints responding
- [ ] Prometheus metrics configured for alerting
- [ ] Log aggregation configured (e.g. Loki + Grafana)
- [ ] Backup strategy for PostgreSQL volume (`postgres_data`)
- [ ] Backup strategy for MinIO volume (`minio_data`)

### Performance

- [ ] `worker-chunks` replicas scaled to your load
- [ ] PostgreSQL connection pool matches worker count
- [ ] MinIO using persistent volume with sufficient disk space

### Remove from Production

- [ ] Remove `--reload` flag from uvicorn (already done — uses `--workers 2`)
- [ ] No `.env` file committed to git
- [ ] No test/debug routes exposed

---

## 6. Database Migrations

Alembic migrations run automatically on API startup via `alembic upgrade head`. For manual control:

```bash
# Check current migration state
docker compose exec api alembic current

# Apply pending migrations
docker compose exec api alembic upgrade head

# Create a new migration (after changing models.py)
docker compose exec api alembic revision --autogenerate -m "add_new_column"

# Roll back one revision
docker compose exec api alembic downgrade -1
```

### SQLite vs PostgreSQL

In development, the app defaults to SQLite (`sqlite:///./vergabepilot.db`) if `DATABASE_URL` is not set. This works for testing but:
- SQLite does not support concurrent writes from multiple workers
- Always use PostgreSQL in any multi-worker setup

---

## 7. Monitoring

### Prometheus + Grafana Setup

```yaml
# prometheus.yml
scrape_configs:
  - job_name: vergabepilot
    static_configs:
      - targets: ['api:8000']
    metrics_path: /metrics
```

### Key Metrics to Alert On

| Metric | Alert condition |
|---|---|
| `vergabepilot_scrape_total{status="failed"}` rate | > 50% |
| `vergabepilot_circuit_breaker_events_total{event="trip"}` rate | sustained spike (portals down/blocking) |
| `vergabepilot_rate_limit_hits_total` rate | high (workers throttled by limiter) |
| `vergabepilot_http_retries_total` rate | high (flaky upstreams) |
| PostgreSQL connections | > 35 (near pool limit) |
| MinIO disk usage | > 80% |
| Redis memory | > 400 MB |

> Three Celery Beat jobs keep long runs healthy: `crash_recovery` (every 10 min, rescues zombie jobs), `check_document_versions` (every `VERSIONING_CHECK_INTERVAL_HOURS`, default 24 h), and `cleanup_stale_downloads` (hourly, removes download dirs > 24 h old to prevent disk exhaustion on 10K-URL runs).

### Log Aggregation

Structured JSON logs from the API:
```bash
# View structured logs
docker compose logs api | python3 -m json.tool
```

All events also appear in the audit log at `GET /api/audit`.

---

## 8. Troubleshooting

### API container keeps restarting

```bash
docker logs vergabepilot-ai-api-1 --tail 30
```

Common causes:
- **`[VERGABEPILOT STARTUP ERROR]`** — insecure credentials in `.env`. Set `VERGABEPILOT_ENV=development` or fix the credentials.
- **`could not connect to server`** — PostgreSQL not ready. Run `docker compose up postgres redis minio` first, wait for healthy, then start API.
- **`alembic upgrade head` fails** — migration conflict. Check `alembic current` and resolve manually.

### MinIO container crashes on start

Usually caused by using a pinned older MinIO image with a data volume written by a newer version:
```bash
# Check the error
docker logs vergabepilot-ai-minio-1

# Fix: use latest MinIO
# In docker-compose.yml, ensure: image: minio/minio:latest
docker compose up -d minio
```

### Workers processing very slowly

1. Check Redis queue depth: `docker compose exec redis redis-cli llen celery`
2. Check `JOB_CONCURRENCY` — increase from 8 to 16 or 32
3. Scale `worker-chunks`: `docker compose up --scale worker-chunks=4 -d`
4. Check if LLM calls are the bottleneck: `LLM_GLOBAL_CONCURRENCY=16`

### Documents not appearing after job completes

1. Check MinIO is healthy: `curl localhost:9000/minio/health/live`
2. Check bucket exists: log into MinIO console at `:9001`
3. Check document records in DB: `GET /api/jobs/{id}/documents`
4. Look for storage errors in audit log: `GET /api/audit?level=error`

### Port conflicts

```bash
# Check what's using port 8000
lsof -i :8000

# Change API port in docker-compose.yml
ports:
  - "8001:8000"  # Map to 8001 externally
```
