/**
 * Shared TypeScript types mirroring the FastAPI Pydantic schemas.
 *
 * These types are manually kept in sync with the backend schemas.py.
 * If you add a field to a Pydantic model, add it here too so TypeScript
 * can catch missing usages at compile time.
 *
 * Naming convention: snake_case everywhere — matches the JSON the backend sends
 * so we don't need any camelCase conversion layer.
 */

/** Possible states a Job or JobItem can be in. */
export type JobStatus = "pending" | "running" | "success" | "partial" | "failed";

/** A scraping job — one or more URLs submitted together. */
export interface Job {
  id: string;
  created_at: string;       // ISO-8601 UTC timestamp
  updated_at: string;
  status: JobStatus;
  submitted_by?: string;    // free-text label set by the caller (e.g. email or "upload:batch.csv")
  total_urls: number;       // count of URLs at submission time
  completed: number;        // count of items in SUCCESS state
  cost_usd: number;         // cumulative LLM cost across all items
  domains?: string[];       // unique domain list (populated by list endpoint, not detail)
  first_url?: string;       // convenience field for list-view display
  items?: JobItem[];        // only present in the detail endpoint response
}

/** A single URL within a Job — one row of work for the pipeline. */
export interface JobItem {
  id: string;
  job_id: string;
  url: string;
  domain: string;
  status: JobStatus;
  strategy: string;         // which strategy finally succeeded: "existing_scraper", "llm_generated_scraper", etc.
  iterations: number;       // number of generate→validate→execute cycles used
  runtime_seconds: number;  // wall-clock time for all strategy attempts combined
  error_message?: string;   // last error string (truncated to 4000 chars in DB)
  failure_category?: string; // error category from core.security.classify_error
  attempts_detail?: AttemptRecord[]; // per-strategy attempt breakdown (not always populated)
  document_count?: number;  // number of documents downloaded for this item
}

/** One strategy attempt within a JobItem's cascade. */
export interface AttemptRecord {
  strategy: string;         // strategy key (e.g. "deterministic_template")
  success: boolean;
  downloaded: number;       // count of documents downloaded in this attempt
  duration_s: number;       // wall-clock seconds for this specific attempt
  timestamp: string;        // ISO-8601 UTC when this attempt ran
  error_raw?: string;       // raw exception message or stderr tail
  error_category?: string;  // classified error type
  error_reason?: string;    // human-readable explanation of why it failed
}

/** A procurement document downloaded by the pipeline. */
export interface Document {
  id: string;
  job_item_id: string;     // the parent URL item
  filename: string;
  s3_key: string;           // object key in MinIO/S3 bucket
  mime_type: string;
  size_bytes: number;
  version: number;          // incremented when the same filename is downloaded again (versioning)
  checksum: string;         // SHA-256 hex digest for deduplication
  created_at: string;
  download_url?: string;    // injected by the API response (presigned S3 URL or local path)
}

/** A reusable scraper stored in the Phase 3 scraper registry. */
export interface ScraperTemplate {
  id: string;
  domain: string;           // e.g. "www.dtvp.de"
  code: string;             // Python source of the `scrape(url, output_dir)` function
  language: string;         // always "python3" currently
  source: string;           // "disk" | "llm" | "manual" | "cua"
  platform?: string;        // detected platform: "dtvp", "netserver", "evergabe", etc.
  success_count: number;    // successful executions (used for health rating)
  failure_count: number;    // failed executions
  avg_runtime: number;      // exponential moving average of execution time (seconds)
  created_at: string;
}

/** Aggregated KPIs returned by GET /api/admin/stats. */
export interface AdminStats {
  jobs: number;             // total jobs ever created
  items: number;            // total URL items ever processed
  succeeded: number;        // items in SUCCESS state
  failed: number;           // items in FAILED state
  pending: number;          // items in PENDING or RUNNING state
  total_cost_usd: number;   // cumulative LLM API spend
  item_success_rate: number; // succeeded / items (0–1)
  scraper_templates: number; // scrapers in the registry
  /** Count of items per strategy key. */
  strategy_distribution: Record<string, number>;
  /** Count of SUCCESSFUL items per strategy key. */
  strategy_success_distribution: Record<string, number>;
  /** Coarse outcome-bucket counts (success/auth_gated/captcha/…). */
  outcome_buckets?: Record<string, number>;
  /** Human label per outcome bucket key. */
  outcome_bucket_labels?: Record<string, string>;
  /** Items whose only path forward is a human (login / CAPTCHA). */
  needs_manual_count?: number;
  /** Detailed failure-category counts (for the admin dashboard). */
  error_categories?: Record<string, number>;
}

/** One item from GET /api/jobs/needs-manual. */
export interface NeedsManualItem {
  job_id: string;
  item_id: string;
  url: string;
  domain: string;
  failure_category: string;
  bucket: string;
  bucket_label: string;
  reason: string;
  suggested_action: string;
  retry_url: string;
}

/** Response shape of GET /api/jobs/needs-manual. */
export interface NeedsManualResponse {
  total: number;
  items: NeedsManualItem[];
}

/** One row from the audit_logs table. */
export interface AuditLog {
  id: string;
  created_at: string;
  level: "info" | "warning" | "error" | "critical";
  event_type: string;       // e.g. "pipeline.strategy_attempt", "job.stopped"
  job_id?: string;
  item_id?: string;
  domain?: string;
  url?: string;
  strategy?: string;        // strategy key at the time of the event
  message: string;          // human-readable event description (≤4000 chars)
  extra: Record<string, unknown>; // arbitrary metadata attached by the writer
}

/** Structured extraction result for a completed JobItem. */
export interface ExtractionRecord {
  id: string;
  job_item_id: string;
  source_url: string;
  docs_parsed: number;       // how many documents were parsed to extract these fields
  runtime_seconds: number;
  created_at: string;
  fields: TenderFields;
}

/**
 * Structured fields extracted from German public procurement tender documents.
 *
 * Field names follow German administrative terminology (Vergabenummer = tender ID,
 * Auftraggeber = contracting authority, etc.) to match the source document language
 * and make the output directly usable by German-speaking procurement teams.
 *
 * All fields are optional — extraction quality depends on document completeness.
 */
export interface TenderFields {
  vergabenummer?: string;         // tender reference number (e.g. "VgV-2024-0042")
  ted_reference?: string;         // EU TED publication reference (e.g. "2024/S 123-456789")
  auftraggeber?: string;          // contracting authority name
  vergabestelle?: string;         // awarding body / procurement office
  titel?: string;                 // tender title / subject of contract
  vergabeverfahren?: string;      // procedure type (Offenes Verfahren, VgV, etc.)
  auftragsart?: string;           // contract type (Liefer-, Dienst-, Bauauftrag)
  veroeffentlichungsdatum?: string; // publication date (ISO-8601 or free text)
  abgabefrist?: string;           // submission deadline
  bindefrist?: string;            // bid validity period
  cpv_codes?: string[];           // CPV codes (EU Common Procurement Vocabulary)
  nuts_codes?: string[];          // NUTS geographic codes (e.g. "DE212")
  auftragswert?: string;          // estimated contract value
  waehrung?: string;              // currency (default EUR)
  leistungsort?: string;          // place of performance
  laufzeit?: string;              // contract duration
  ansprechpartner?: string;       // contact person name
  email?: string;
  telefon?: string;
  fax?: string;
  zuschlagskriterien?: string[];  // award criteria (e.g. "Preis 60%, Qualität 40%")
  eignungskriterien?: string[];   // eligibility requirements
  lose?: string[];                // lots if the contract is divided
  additional_notes?: string[];    // free-form notes extracted from document headers
}

// ── Public tender directory ────────────────────────────────────────────────
// Mirrors app/api/routes_directory.py. Read-only, public, whitelisted fields.

/** A domain in the public directory, with its count of currently-open tenders. */
export interface DirectoryDomain {
  domain: string;
  open_count: number;
  site_url: string;   // official portal URL — opened directly when the domain is clicked
}

/** Tender lifecycle state shown in the directory (derived from the deadline). */
export type TenderDirectoryStatus = "open" | "closing_soon" | "deadline_unknown";

/** A single open tender in the public directory — public-safe fields only. */
export interface DirectoryTender {
  job_id: string;
  item_id: string;
  title: string | null;
  reference: string | null;
  deadline: string | null;        // ISO-8601 UTC, or null when unknown
  status: TenderDirectoryStatus;
  url: string;
}

/** Paginated response for GET /directory/domains/{domain}/tenders. */
export interface DirectoryTendersResponse {
  domain: string;
  total: number;
  limit: number;
  offset: number;
  tenders: DirectoryTender[];
}
