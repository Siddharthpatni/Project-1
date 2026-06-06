/**
 * Shared TypeScript types for all API responses.
 */

export type JobStatus = "pending" | "running" | "success" | "partial" | "failed";

export interface Job {
  id: string;
  created_at: string;
  updated_at: string;
  status: JobStatus;
  submitted_by?: string;
  total_urls: number;
  completed: number;
  cost_usd: number;
  domains?: string[];
  first_url?: string;
  items?: JobItem[];
}

export interface JobItem {
  id: string;
  job_id: string;
  url: string;
  domain: string;
  status: JobStatus;
  strategy: string;
  iterations: number;
  runtime_seconds: number;
  error_message?: string;
  failure_category?: string;
  attempts_detail?: AttemptRecord[];
  document_count?: number;
}

export interface AttemptRecord {
  strategy: string;
  success: boolean;
  downloaded: number;
  duration_s: number;
  timestamp: string;
  error_raw?: string;
  error_category?: string;
  error_reason?: string;
}

export interface Document {
  id: string;
  job_item_id: string;
  filename: string;
  s3_key: string;
  mime_type: string;
  size_bytes: number;
  version: number;
  checksum: string;
  created_at: string;
  download_url?: string;
}

export interface ScraperTemplate {
  id: string;
  domain: string;
  code: string;
  language: string;
  source: string;
  platform?: string;
  success_count: number;
  failure_count: number;
  avg_runtime: number;
  created_at: string;
}

export interface AdminStats {
  jobs: number;
  items: number;
  succeeded: number;
  failed: number;
  pending: number;
  total_cost_usd: number;
  item_success_rate: number;
  scraper_templates: number;
  strategy_distribution: Record<string, number>;
  strategy_success_distribution: Record<string, number>;
}

export interface AuditLog {
  id: string;
  created_at: string;
  level: "info" | "warning" | "error" | "critical";
  event_type: string;
  job_id?: string;
  item_id?: string;
  domain?: string;
  url?: string;
  strategy?: string;
  message: string;
  extra: Record<string, unknown>;
}

export interface ExtractionRecord {
  id: string;
  job_item_id: string;
  source_url: string;
  docs_parsed: number;
  runtime_seconds: number;
  created_at: string;
  fields: TenderFields;
}

export interface TenderFields {
  vergabenummer?: string;
  ted_reference?: string;
  auftraggeber?: string;
  vergabestelle?: string;
  titel?: string;
  vergabeverfahren?: string;
  auftragsart?: string;
  veroeffentlichungsdatum?: string;
  abgabefrist?: string;
  bindefrist?: string;
  cpv_codes?: string[];
  nuts_codes?: string[];
  auftragswert?: string;
  waehrung?: string;
  leistungsort?: string;
  laufzeit?: string;
  ansprechpartner?: string;
  email?: string;
  telefon?: string;
  fax?: string;
  zuschlagskriterien?: string[];
  eignungskriterien?: string[];
  lose?: string[];
  additional_notes?: string[];
}
