"""
Prometheus metrics for the Vergabepilot pipeline.

All counters/histograms are module-level singletons — safe to import from
multiple threads/coroutines because prometheus_client uses its own internal
locks. Import this module once at startup; calling code increments counters
directly without needing to re-import.

Graceful degradation: if prometheus_client is not installed the module still
imports cleanly — all metric objects become no-op stubs so no code path
changes are required.
"""
from __future__ import annotations

try:
    from prometheus_client import (  # type: ignore
        Counter,
        Histogram,
        Gauge,
        REGISTRY,
    )
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

    # Minimal no-op stubs so callers never see ImportError
    class _Stub:
        def labels(self, **_): return self
        def inc(self, *_, **__): pass
        def observe(self, *_, **__): pass
        def set(self, *_, **__): pass

    def Counter(*_, **__): return _Stub()   # type: ignore
    def Histogram(*_, **__): return _Stub() # type: ignore
    def Gauge(*_, **__): return _Stub()     # type: ignore


# ---------------------------------------------------------------------------
# Scrape / strategy metrics
# ---------------------------------------------------------------------------

SCRAPE_TOTAL = Counter(
    "vergabepilot_scrape_total",
    "Total scrape attempts by strategy and outcome",
    ["strategy", "status"],   # status: success | failed
)

SCRAPE_DURATION = Histogram(
    "vergabepilot_scrape_duration_seconds",
    "Wall-clock time per scrape attempt",
    ["strategy"],
    buckets=[1, 5, 10, 20, 30, 45, 60, 90, 120, 180],
)

# ---------------------------------------------------------------------------
# Document / storage metrics
# ---------------------------------------------------------------------------

DOCUMENTS_DOWNLOADED = Counter(
    "vergabepilot_documents_downloaded_total",
    "Total documents successfully downloaded and persisted",
    ["mime_type"],
)

ZIP_EXPANSIONS = Counter(
    "vergabepilot_zip_expansions_total",
    "ZIPs expanded; files_extracted is the number of files produced",
)

ZIP_FILES_EXTRACTED = Counter(
    "vergabepilot_zip_files_extracted_total",
    "Total individual files extracted from ZIP archives",
)

# ---------------------------------------------------------------------------
# LLM / scraper generation metrics
# ---------------------------------------------------------------------------

LLM_GENERATIONS = Counter(
    "vergabepilot_llm_generations_total",
    "Total LLM scraper generation attempts",
    ["model", "status"],   # status: success | failed | loop_exhausted
)

SANDBOX_EXECUTIONS = Counter(
    "vergabepilot_sandbox_executions_total",
    "Total sandboxed subprocess executions",
    ["outcome"],   # outcome: success | no_documents | crash | timeout
)

SANDBOX_DURATION = Histogram(
    "vergabepilot_sandbox_duration_seconds",
    "Time spent inside the sandbox subprocess",
    buckets=[1, 5, 10, 15, 25, 45, 60, 90, 120],
)

SCRAPER_REGISTRY_SIZE = Gauge(
    "vergabepilot_scraper_registry_domains",
    "Number of domains with a scraper in the registry",
)

# ---------------------------------------------------------------------------
# Job metrics
# ---------------------------------------------------------------------------

ACTIVE_JOBS = Gauge(
    "vergabepilot_active_jobs",
    "Number of jobs currently in running state",
)

JOB_URLS_PROCESSED = Counter(
    "vergabepilot_job_urls_processed_total",
    "Total URL items processed across all jobs",
    ["status"],   # status: success | failed | partial
)

# ---------------------------------------------------------------------------
# Extraction metrics
# ---------------------------------------------------------------------------

EXTRACTION_RUNS = Counter(
    "vergabepilot_extraction_runs_total",
    "Total deep-extraction runs",
    ["status"],   # success | failed
)

EXTRACTION_FIELDS_FOUND = Histogram(
    "vergabepilot_extraction_fields_found",
    "Number of structured procurement fields extracted per run",
    buckets=[0, 1, 3, 5, 8, 10, 12, 15, 18],
)


def is_available() -> bool:
    return _AVAILABLE
