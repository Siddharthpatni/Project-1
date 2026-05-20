# Bug Fixes & Hardening — Vergabepilot.AI Backend

This patch makes the backend actually able to generate, validate, run, and
persist scrapers end-to-end. The architecture in `docs/ARCHITECTURE.md` is
unchanged — the file layout was already correct; the bugs were inside the
modules.

## Critical fixes (without these, no scraper can succeed)

### 1. Downloads were being silently destroyed
**File:** `app/phase1_llm_scraper/executor.py`

The old executor wrote downloads into a `tempfile.TemporaryDirectory()` that
was deleted at function exit. A comment said "Move downloads out of the temp
dir so caller can keep them" but no move actually happened. Even when a
generated scraper worked perfectly, every file vanished by the time the
caller looked at the returned paths.

**Fix:** Scrapers now write into a persistent `output_dir` under
`settings.downloads_dir` (with `tempfile.gettempdir()/vergabepilot-downloads`
as fallback for local dev where `/app/data/downloads` doesn't exist). Only
the workdir holding `scraper.py` + `result.json` is cleaned up at function
exit. Added `cleanup_output_dir()` helper that the feedback loop and
pipeline call after they're done with the files.

The new `ExecutionResult` carries an `output_dir` field so callers know
which directory to clean up.

The runner template now also accepts both legal return shapes from
`scrape()`: `list[str]` and `{"downloaded_files": [...]}`.

### 2. Sandboxed scrapers couldn't import any libraries
**File:** `app/core/sandbox.py`

The old sandbox set `PYTHONPATH = workdir` and stripped every other env var.
Generated scrapers all failed with `ImportError: No module named playwright`
(or `requests`, `bs4`, `lxml`, ...) before they could run a single line.

**Fix:** PYTHONPATH now extends with `site.getsitepackages()`,
`site.getusersitepackages()`, and `sys.path` — the same import paths the
host interpreter uses — so installed libraries are reachable. The host
environment is otherwise inherited so locale, Playwright browser paths, etc.
work, but `_SENSITIVE_ENV_PREFIXES` are still stripped (AWS_, ANTHROPIC_,
OPENAI_, GOOGLE_, OPENROUTER_, MINIO_, DATABASE_URL, REDIS_, SECRET_, S3_,
plus explicit token names) so scrapers cannot exfiltrate credentials.

Also tightened the timeout-kill path with a small `communicate(timeout=5)`
guard so a hung subprocess can't wedge the worker.

### 3. Pipeline lost track of files between strategies
**File:** `app/phase3_integration/pipeline.py`

Each strategy's runner returned absolute paths, but they referenced
about-to-be-deleted temp dirs (or in `_try_manual`'s case, a partially
working ad-hoc copy). `_persist_documents` was then called against
non-existent paths.

**Fix:** The pipeline now creates one canonical scratch directory per
job-item (`<downloads_dir>/job-<job_id>-<item_id>`). Every strategy calls
`_move_into(scratch, sources)` which copies files out of the strategy's
private temp area into the scratch dir, deduping filenames on collision.
Persistence reads from the scratch dir and the scratch dir is wiped after
S3 upload.

Also added:
- SSRF/scheme guard via `core.security.is_url_allowed` at entry
- Phase-1 feedback loop runs via `asyncio.to_thread` (it does sync I/O)
- S3 failures are logged but don't abort the job
- Per-item exception handling in tasks so one bad URL doesn't kill the rest

### 4. Feedback loop leaked output dirs
**File:** `app/phase1_llm_scraper/feedback_loop.py`

Each failed iteration left an empty output directory on disk forever.

**Fix:** Failed iterations are cleaned up immediately. The successful
iteration's directory is preserved and handed off via
`final_execution.output_dir`.

## Secondary fixes

### 5. ObjectStorage crashed on construction if MinIO was down
**File:** `app/core/storage.py`

`_ensure_bucket` did a `head_bucket` HTTP call at `__init__` time. If MinIO
wasn't running (typical in local dev or first boot), every API request and
every Celery task crashed with a connection error.

**Fix:** Construction is now soft — connection failures fall back to local
disk under `<downloads_dir>/_s3_fallback/<key>`. `put`, `get`, `presign`,
and `delete` retry-fall-back transparently. Connect/read timeouts capped at
5/10s with no boto3 retries so a slow S3 doesn't hang the pipeline.

### 6. ScraperTemplate disk mirror used a hardcoded path
**File:** `app/phase3_integration/scraper_registry.py`

The old code wrote successful scrapers to `UNi/Phase-1/generated_scrapers`
relative to `__file__` — a path that exists only in the original developer's
checkout. On any other machine it raised, was caught, and the disk mirror
was lost.

**Fix:** Uses `settings.scraper_registry_path` (which defaults to
`/app/data/scrapers` in Docker) with `tempfile.gettempdir()/vergabepilot-scrapers`
as fallback. Domain is sanitized with a regex so `..` etc. can't escape the
directory.

### 7. Enums were assigned as objects to string columns
**File:** `app/api/routes_jobs.py`, `app/api/routes_admin.py`

Code was doing `Job(status=JobStatus.PENDING)` (the enum member) and
`JobItem.status == JobStatus.SUCCESS` (the enum, not its value). SQLAlchemy
uses `String` columns for these, so the comparison sometimes worked and
sometimes didn't depending on dialect coercion. Stats and admin endpoints
returned wrong counts.

**Fix:** All enum reads/writes go via `.value` consistently.

### 8. Versioning task referenced a nonexistent helper
**File:** `app/workers/tasks.py`

`check_document_versions_task` was a no-op stub that didn't even use the
registry. Now iterates registry templates, skips retired ones, and counts
checked domains. Per-domain re-checks are intentionally not done inline (to
avoid blocking beat); a future per-domain task would be enqueued here.

### 9. Hardened generator prompts
**File:** `app/phase1_llm_scraper/prompts.py`

Added:
- Concrete `from playwright.sync_api import sync_playwright` import line so
  models don't pick `async_api` and break the sync runner
- Explicit ban on importing `subprocess`, `socket`, `ctypes`,
  `multiprocessing` (these match the validator's deny-list)
- A short skeleton showing the expected structure
- Tighter timeout guidance (60s budget, 5-10s per request)
- Required try/except around the `scrape()` body so one bad link doesn't
  fail the whole run

## Verification

All 17 existing unit tests still pass.

End-to-end validations performed:
1. Executor sanity test — 3 fake files written by a scraper survive
   `execute()` returning, are visible to the caller, and `cleanup_output_dir`
   correctly removes them.
2. Sandbox import test — a scraper that imports `requests`, `bs4`, `lxml`
   inside the sandbox runs successfully (would have raised `ImportError`
   before the sandbox fix).
3. Validator regression — `subprocess`, `eval`, `exec`, `os.system`, `socket`
   imports, and missing `scrape()` function are all still rejected; valid
   scrapers still pass.
4. Phase-1 feedback loop — with a mock LLM returning a working scraper,
   loop completes in 1 iteration, recall=1.0, files survive.
5. Phase-3 cascade — full `process_url` run with mock LLM ends with
   `success=True`, 2 `Document` rows in the DB with correct s3_keys, sizes,
   and checksums; `ScraperTemplate` is upserted to the registry; scratch
   dirs are cleaned up.
6. FastAPI app loads cleanly with all 25 routes wired.

## Files changed

- `backend/app/core/sandbox.py`
- `backend/app/core/storage.py`
- `backend/app/phase1_llm_scraper/executor.py`
- `backend/app/phase1_llm_scraper/feedback_loop.py`
- `backend/app/phase1_llm_scraper/prompts.py`
- `backend/app/phase3_integration/pipeline.py`
- `backend/app/phase3_integration/scraper_registry.py`
- `backend/app/api/routes_jobs.py`
- `backend/app/api/routes_admin.py`
- `backend/app/workers/tasks.py`
