# Architecture — Vergabepilot.AI

## Table of Contents
1. [High-Level Overview](#1-high-level-overview)
2. [Component Diagram](#2-component-diagram)
3. [Request Lifecycle](#3-request-lifecycle)
4. [Database Schema](#4-database-schema)
5. [Worker Architecture](#5-worker-architecture)
6. [Storage Architecture](#6-storage-architecture)
7. [Security Architecture](#7-security-architecture)
8. [Observability](#8-observability)

---

## 1. High-Level Overview

Vergabepilot.AI is a **multi-tier, event-driven system** built around an Agentic Cascade Pipeline. Every layer is independently scalable and isolated via Docker.

| Tier | Technology | Role |
|---|---|---|
| Presentation | Next.js 14 (App Router) | Real-time dashboard, job submission, analytics |
| API Gateway | FastAPI + Uvicorn (2 workers) | REST API, request routing, health probes |
| Task Queue | Celery + Redis | Async job orchestration, fan-out to worker pools |
| Cascade Engine | Phase 0–3 Python modules | Scraping strategy execution |
| Persistence | PostgreSQL 16 | Relational data (jobs, items, audit, scrapers) |
| Object Storage | MinIO (S3-compatible) | Downloaded procurement documents |
| LLM Provider | OpenRouter → Gemini 2.5 Flash Lite | Code generation, field extraction |

```mermaid
graph LR
    subgraph Browser
        UI[Next.js SPA<br/>:3000]
    end

    subgraph Docker_Network["Docker Network"]
        API[FastAPI<br/>:8000]
        PG[(PostgreSQL<br/>:5432)]
        RD[(Redis<br/>:6379)]
        MN[(MinIO<br/>:9000)]

        subgraph Workers
            WD[worker-default<br/>concurrency=4]
            WC1[worker-chunks-1<br/>concurrency=16]
            WC2[worker-chunks-2<br/>concurrency=16]
            WQ[worker-cua<br/>concurrency=2]
            BT[Celery Beat]
        end
    end

    subgraph External
        OR[OpenRouter<br/>Gemini API]
        PT[Procurement<br/>Portals]
    end

    UI --> API
    API --> PG & MN & RD
    RD --> WD
    WD -->|fan-out| WC1 & WC2
    WC1 & WC2 -->|HTTP / Playwright| PT
    WC1 & WC2 -->|LLM calls| OR
    WQ -->|browser-use| PT
    WD & WC1 & WC2 --> PG & MN
    BT --> RD
```

---

## 2. Component Diagram

### Backend Module Map

```mermaid
graph TB
    subgraph API["app/api — Route Handlers"]
        RJ[routes_jobs.py]
        RS[routes_scrapers.py]
        RA[routes_admin.py]
        RAU[routes_audit.py]
        RE[routes_extractor.py]
        REV[routes_evaluation.py]
        RAG[routes_agents.py]
        RT[routes_tests.py]
    end

    subgraph Phase0["app/phase0_manual"]
        V1[v1_reference.py<br/>Playwright manual scraper]
    end

    subgraph Phase1["app/phase1_llm_scraper"]
        GEN[generator.py — LLM prompt + code builder]
        SBX[executor.py — sandboxed PySandbox runner]
        FBK[feedback_loop.py — iterative self-healing]
        VAL[validator.py — code safety + SSRF checks]
        EVL[evaluator.py — benchmark runner]
        RLN[route_learner.py — CUA trace recorder]
    end

    subgraph Phase2["app/phase2_cua"]
        PCA[browser_agent.py — Playwright CUA]
        BUA[browser_use_agent.py — browser-use CUA]
        ORC[orchestrator.py — agent dispatcher]
    end

    subgraph Phase3["app/phase3_integration"]
        PPL[pipeline.py — cascade orchestrator]
        REG[scraper_registry.py — save/load scrapers]
        DET[deterministic.py — direct ZIP download]
        PCF[platform_classifier.py — portal detection]
        VER[versioning.py — document change tracking]
        FLB[fallback.py — next-strategy selector]
    end

    subgraph Core["app/core"]
        SEC[security.py — SSRF + injection guards]
        STR[storage.py — MinIO S3 client]
        MET[metrics.py — Prometheus counters]
        ZXP[zip_expander.py — recursive ZIP handler]
    end

    subgraph Extractor["app/document_extractor"]
        EXT[extractor.py — orchestrator]
        FLD[field_extractor.py — 50+ regex patterns]
        PAR[parsers.py — PDF/DOCX/XLSX text extraction]
        LLM[llm_enhancer.py — Gemini field boost]
        RPT[report_builder.py — PDF/DOCX report gen]
    end

    RJ --> PPL
    PPL --> V1 & GEN & DET & ORC & REG & SEC & STR
    GEN --> SBX --> FBK
    EXT --> FLD & PAR & LLM & RPT
    RE --> EXT
```

### Frontend Page Map

```mermaid
graph TB
    subgraph Pages["app/ — Pages (Next.js App Router)"]
        PH[/ — Dashboard]
        PJ[/jobs — Job List]
        PJD["/jobs/[id] — Job Detail"]
        PX[/extraction — Deep Extraction]
        PS[/scrapers — Scraper Registry]
        PA[/audit — Audit Log]
        PM[/admin — System Health]
        PG[/agents — CUA Sessions]
        PV[/evaluation — LLM Benchmarks]
        PE[/excel — Excel Workspace]
        PT[/tests — Test Runner]
        P4[/not-found — 404 Page]
    end

    subgraph Shared["components/"]
        NAV[Navbar — sticky, theme toggle]
        JSF[JobSubmitForm — URL + file upload]
        SBG[StatusBadge — animated status pills]
        TOS[Toast + ToastProvider]
        DSY[ui/index.tsx — Full Design System]
    end

    subgraph Lib["lib/"]
        AC[api.ts — fetcher with retry + backoff]
        HK[hooks.ts — useTheme, useDebounce]
        TY[types.ts — TypeScript interfaces]
        TH[theme.ts — design tokens]
    end

    PH --> JSF & AC
    PJ --> SBG & AC
    PJD --> SBG & DSY & TOS & AC
    PA --> TOS & AC
    PM --> TOS & AC
    NAV -.->|wraps all pages| PH
    TOS -.->|wraps all pages| PH
```

---

## 3. Request Lifecycle

### Job Submission (Happy Path)

```mermaid
sequenceDiagram
    actor User
    participant UI as Next.js
    participant API as FastAPI
    participant PG as PostgreSQL
    participant RD as Redis
    participant WD as worker-default
    participant WC as worker-chunks (×2)
    participant PPL as Cascade Pipeline
    participant MN as MinIO

    User->>UI: Paste URLs → Submit
    UI->>API: POST /api/jobs {urls:[...]}
    API->>PG: INSERT Job + N×JobItem (status=pending)
    API->>RD: enqueue process_job_task(job_id)
    API-->>UI: 201 {id, status:"pending"}
    UI-->>User: Redirect → /jobs/{id}

    loop Poll every 2s while running
        UI->>API: GET /api/jobs/{id}
        API->>PG: SELECT job + items
        API-->>UI: {completed, total, items:[...]}
    end

    RD->>WD: dequeue process_job_task
    WD->>PG: load job URLs

    alt Large job > 50 URLs
        WD->>RD: enqueue N×process_chunk_task
        WC->>PPL: process_url() per chunk (parallel)
    else Small job ≤ 50 URLs
        WD->>PPL: process_url() directly
    end

    PPL->>PPL: run cascade (see Pipeline doc)
    PPL->>MN: PUT downloaded documents
    PPL->>PG: UPDATE JobItem (strategy, status, attempts_detail)
    WD->>PG: UPDATE Job.completed++, Job.status
```

---

## 4. Database Schema

```mermaid
erDiagram
    JOB {
        string id PK
        datetime created_at
        datetime updated_at
        string status
        string submitted_by
        int total_urls
        int completed
        float cost_usd
    }

    JOB_ITEM {
        string id PK
        string job_id FK
        text url
        string domain
        string status
        string strategy
        int iterations
        text error_message
        string failure_category
        json attempts_detail
        float runtime_seconds
    }

    DOCUMENT {
        string id PK
        string job_item_id FK
        string filename
        string s3_key
        string mime_type
        int size_bytes
        int version
        string checksum
        datetime created_at
    }

    SCRAPER_TEMPLATE {
        string id PK
        string domain
        text code
        string source
        string platform
        bool route_used
        text cua_hint
        int success_count
        int failure_count
        float avg_runtime
        datetime created_at
        datetime updated_at
    }

    EXTRACTION_RECORD {
        string id PK
        string job_item_id FK
        text source_url
        text fields_json
        int docs_parsed
        float runtime_seconds
        datetime created_at
        datetime updated_at
    }

    AUDIT_LOG {
        string id PK
        datetime created_at
        string level
        string event_type
        string job_id
        string domain
        text url
        string strategy
        text message
        json extra
    }

    EVALUATION_RUN {
        string id PK
        string model
        text url
        int expected_docs
        int downloaded_docs
        bool success
        int iterations
        float cost_usd
    }

    AGENT_RUN {
        string id PK
        string agent_name
        text url
        int steps
        bool success
        float cost_usd
        json trace
    }

    JOB ||--o{ JOB_ITEM : "1-to-many"
    JOB_ITEM ||--o{ DOCUMENT : "1-to-many"
    JOB_ITEM ||--o| EXTRACTION_RECORD : "0-to-1"
```

**Design Notes:**
- `AuditLog` is **append-only** — no UPDATE or DELETE, ever. Full event replay is always possible.
- `attempts_detail` is a JSON array on `JobItem` storing every strategy tried, its outcome, duration, and error. No extra join needed for the UI timeline.
- `ScraperTemplate.cua_hint` stores the CUA interaction trace as text, used as additional context for future LLM scraper generation on that domain.
- PostgreSQL connection pool: `pool_size=20, max_overflow=20` → 40 total connections, enough for 32 concurrent workers.

---

## 5. Worker Architecture

```mermaid
graph LR
    subgraph Queues["Redis Queues"]
        QD[queue: default]
        QC[queue: chunks]
        QU[queue: cua]
    end

    subgraph WD_Pool["worker-default (×1, concurrency=4)"]
        T1[process_job_task<br/>orchestrate + fan-out]
        T2[finalize_job_task<br/>aggregate results]
        T3[rescue_stale_jobs<br/>startup recovery]
    end

    subgraph WC_Pool["worker-chunks (×2, concurrency=16)"]
        T4[process_chunk_task<br/>parallel URL batch]
    end

    subgraph WQ_Pool["worker-cua (×1, concurrency=2)"]
        T5[run_cua_agent_task<br/>visual browser session]
    end

    subgraph Beat["Celery Beat (×1)"]
        S1[rescue_stale_jobs — every 5min]
        S2[check_versions — every 24h]
    end

    QD --> WD_Pool
    QC --> WC_Pool
    QU --> WQ_Pool
    Beat --> QD
```

| Pool | Replicas | Concurrency | Total slots | Role |
|---|---|---|---|---|
| worker-default | 1 | 4 | 4 | Job orchestration, fan-out |
| worker-chunks | 2 | 16 | **32** | URL processing (main throughput) |
| worker-cua | 1 | 2 | 2 | Browser-heavy CUA sessions |

Scale for more throughput:
```bash
# Double throughput to 64 simultaneous URLs
docker compose up --scale worker-chunks=4 -d
```

---

## 6. Storage Architecture

```mermaid
graph TB
    subgraph S3["MinIO Bucket: vergabepilot-documents"]
        K1["jobs/{job_id}/{item_id}/{filename}.pdf"]
        K2["jobs/{job_id}/{item_id}/{filename}.zip"]
        K3["jobs/{job_id}/{item_id}/extracted/{inner}.pdf"]
    end

    subgraph Fallback["Local Fallback (MinIO unavailable)"]
        LF["/app/data/downloads/_s3_fallback/jobs/{job_id}/"]
    end

    subgraph Registry["Scraper Registry (disk)"]
        SR["/app/data/scrapers/scraper_{domain}.py"]
    end

    PPL[Cascade Pipeline] -->|PUT object| S3
    PPL -->|fallback write| Fallback
    PPL -->|save scraper| Registry
    S3 --> DOC[documents table<br/>s3_key + checksum + version]
```

**Document versioning:** SHA-256 checksums detect portal updates. Changed files increment `Document.version` instead of overwriting, preserving history.

**ZIP expansion:** Recursive extraction up to depth 3, max 500 MB total, 200 MB per file. Path traversal is prevented by stripping `../` sequences.

---

## 7. Security Architecture

```mermaid
flowchart TD
    URL[Incoming URL] --> A{SSRF Check}
    A -- private IP / localhost --> BLOCK[Reject + CRITICAL audit event]
    A -- public URL --> B{Prompt Injection?}
    B -- injection detected --> BLOCK
    B -- clean --> C[Run Scraper]
    C --> D[Sandboxed Execution<br/>timeout=45s · memory=512MB]
    D --> E{Code Safety Validation}
    E -- blocked ops / imports --> BLOCK
    E -- passes --> F[Download Files]
    F --> G{Magic Byte Validation<br/>PDF/ZIP/DOCX/XLSX only}
    G -- HTML or unknown type --> DISCARD[Discard silently]
    G -- valid document --> H{Size Check}
    H -- >200MB per file --> DISCARD
    H -- >500MB total job --> ABORT[Abort job]
    H -- passes --> STORE[Store to MinIO + DB]
```

**Security layers in order:**
1. **SSRF guard** — private IP ranges and `localhost` blocked at URL parsing
2. **Prompt injection detection** — LLM inputs scanned for known injection patterns
3. **Code validation** — generated Playwright code checked for disallowed imports/syscalls
4. **Sandbox execution** — subprocess with `ulimit` on memory + wall-clock timeout
5. **Magic byte validation** — file headers checked regardless of extension
6. **Size limits** — 200 MB per file, 500 MB per job
7. **Secret validation** — startup aborts if `SECRET_KEY` / MinIO credentials are insecure defaults

---

## 8. Observability

### Prometheus Metrics (`GET /metrics`)

| Metric | Type | Labels |
|---|---|---|
| `vergabepilot_scrape_total` | Counter | `strategy`, `status` |
| `vergabepilot_scrape_duration_seconds` | Histogram | `strategy` |
| `vergabepilot_documents_downloaded_total` | Counter | `domain` |
| `vergabepilot_zip_expansions_total` | Counter | — |
| `vergabepilot_llm_generations_total` | Counter | `model`, `status` |
| `vergabepilot_active_jobs` | Gauge | — |
| `vergabepilot_scraper_registry_size` | Gauge | — |
| `vergabepilot_extraction_runs_total` | Counter | `status` |

### Audit Log Event Types

| Level | Event Type | Description |
|---|---|---|
| INFO | `system.startup` | API server started, DB schema synced |
| INFO | `pipeline.start` | Cascade started for one URL |
| INFO | `strategy.success` | A strategy downloaded documents |
| INFO | `scraper.saved` | New scraper registered |
| INFO | `extraction.complete` | Document fields extracted |
| WARNING | `strategy.failure` | A strategy failed; cascade continues |
| ERROR | `pipeline.all_failed` | All 5 strategies exhausted |
| CRITICAL | `security.ssrf_blocked` | SSRF attempt detected and blocked |
| CRITICAL | `security.prompt_injection` | Injection in LLM input detected |
| CRITICAL | `system.unhandled_exception` | Uncaught exception in API handler |

### Health Endpoints

| Endpoint | Checks | Use |
|---|---|---|
| `GET /health` | PostgreSQL connectivity | Liveness probe |
| `GET /ready` | PostgreSQL + Redis | Readiness probe (load balancer) |
| `GET /metrics` | Prometheus text format | Monitoring scrape |
