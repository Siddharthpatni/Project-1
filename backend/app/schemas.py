"""
Pydantic request/response schemas.

Kept in one file because the schema set is small enough that splitting
per-resource adds more indirection than value.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from app.models import JobStatus, Strategy


# -------- Jobs --------

class JobCreateRequest(BaseModel):
    urls: list[HttpUrl] = Field(..., min_length=1, max_length=500)
    submitted_by: str | None = None
    force_strategy: Strategy | None = Field(
        default=None,
        description="Skip the cascade and force a specific strategy (for debugging).",
    )
    force_model: str | None = Field(
        default=None,
        description="Force a specific LLM model to be used by the pipeline.",
    )


class JobItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    url: str
    domain: str
    status: JobStatus
    strategy: Strategy
    iterations: int
    runtime_seconds: float
    error_message: str | None = None
    document_count: int = 0
    attempts_detail: list[dict[str, Any]] = []   # full per-strategy attempt trace


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    updated_at: datetime
    status: JobStatus
    total_urls: int
    completed: int
    cost_usd: float
    items: list[JobItemRead] = []


class JobSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    status: JobStatus
    total_urls: int
    completed: int
    cost_usd: float
    domains: list[str] = []
    first_url: str | None = None


# -------- Documents --------

class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    job_item_id: str | None = None   # added so frontend can group docs per URL
    filename: str
    mime_type: str
    size_bytes: int
    version: int
    download_url: str | None = None


# -------- Scrapers --------

class ScraperTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    domain: str
    code: str
    language: str
    source: str
    platform: str | None = None
    route_used: bool = False
    success_count: int
    failure_count: int
    avg_runtime: float
    created_at: datetime


class ScraperTemplateCreate(BaseModel):
    domain: str
    code: str
    language: str = "python"
    source: str = "manual"


# Route-learning endpoint (POST /api/scrapers/learn)

class LearnRouteRequest(BaseModel):
    url: HttpUrl
    model: str | None = Field(
        default=None,
        description="LLM model to use for generation. Defaults to settings.llm_model_primary.",
    )
    max_clicks: int | None = Field(
        default=None,
        description="How many candidate links/buttons the learner will click. Defaults to settings.route_learning_max_clicks.",
    )
    generate_scraper: bool = Field(
        default=True,
        description="If false, only learn the route without generating a scraper.",
    )


class RouteStepRead(BaseModel):
    action: str
    selector: str | None = None
    text: str | None = None
    url: str | None = None
    description: str = ""
    found_downloads: list[str] = Field(default_factory=list)


class RouteMapRead(BaseModel):
    domain: str
    start_url: str
    steps: list[RouteStepRead]
    document_links: list[str]
    total_documents_found: int
    learned: bool
    error: str | None = None


class LearnRouteResponse(BaseModel):
    domain: str
    platform: str
    route_map: RouteMapRead
    scraper_code: str | None = None
    scraper_id: str | None = None
    documents_found: int
    cost_usd: float = 0.0
    status: str


# -------- Local Files --------

class LocalFileRead(BaseModel):
    filename: str
    size_bytes: int
    domain: str
    job_id: str
    item_id: str
    download_url: str


# -------- Evaluation (phase 1) --------

class EvaluationRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    model: str
    url: str
    expected_docs: int
    downloaded_docs: int
    success: bool
    iterations: int
    runtime_seconds: float
    cost_usd: float


class EvaluationRequest(BaseModel):
    dataset_path: str = Field(..., description="Path to the annotated evaluation dataset JSONL.")
    models: list[str] = Field(..., description="List of LLM model identifiers to benchmark.")
    max_iterations: int = 5


# -------- Agent (phase 2) --------

class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    agent_name: str
    url: str
    steps: int
    success: bool
    runtime_seconds: float
    cost_usd: float
    trace: dict[str, Any]


class AgentRunRequest(BaseModel):
    agent_name: str = "playwright_cua"
    url: HttpUrl
    max_steps: int | None = None
    model_name: str | None = None


# -------- Smart Domain Batch --------

class SmartDomainBatchRequest(BaseModel):
    """
    One primary URL per domain, with an optional backup URL that is
    automatically tried if the primary fails.

    domain_urls: {domain: [primary_url, optional_backup_url]}
    submitted_by: label shown in the job list
    force_strategy: pin the cascade to one strategy (for debugging)
    force_model: pin the LLM model (for debugging)
    """
    domain_urls: dict[str, list[str]] = Field(
        ...,
        description="Map of domain → [primary_url, optional_backup_url]",
    )
    submitted_by: str | None = Field(default=None)
    force_strategy: str | None = Field(default=None)
    force_model: str | None = Field(default=None)


class SmartDomainBatchResult(BaseModel):
    primary_job_id: str
    fallback_job_id: str | None = None
    domains_total: int
    domains_with_backup: int
    status: str


# -------- Audit Log --------

class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    created_at: datetime
    level: str
    event_type: str
    job_id: str | None = None
    item_id: str | None = None
    domain: str | None = None
    url: str | None = None
    strategy: str | None = None
    message: str
    extra: dict[str, Any] = {}

    # alias so the frontend always sees "metadata" regardless of the column rename
    @property
    def metadata(self) -> dict[str, Any]:
        return self.extra


# -------- Test Runner --------

class TestRunRequest(BaseModel):
    suite: str = "all"   # "all" | "phase1" | "phase2" | "phase3" | "platform"


class TestCaseResult(BaseModel):
    name: str
    status: str          # "passed" | "failed" | "error" | "skipped"
    duration_ms: float
    error: str | None = None


class TestRunResult(BaseModel):
    suite: str
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_seconds: float
    cases: list[TestCaseResult]
    raw_output: str
