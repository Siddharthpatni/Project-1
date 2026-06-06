"use client";

import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useState } from "react";
import {
  ScanSearch, FileOutput, Loader2, RefreshCw, CheckCircle2,
  AlertCircle, ChevronDown, ChevronRight, FileText,
  Layers, Download,
} from "lucide-react";

// ── Helpers ──────────────────────────────────────────────────────────

const FIELD_LABELS: Record<string, string> = {
  vergabenummer:           "Vergabenummer",
  ted_reference:           "TED-Referenz",
  auftraggeber:            "Auftraggeber",
  titel:                   "Titel",
  vergabeverfahren:        "Vergabeverfahren",
  auftragsart:             "Auftragsart",
  veroeffentlichungsdatum: "Veröffentlicht",
  abgabefrist:             "Abgabefrist",
  bindefrist:              "Bindefrist",
  cpv_codes:               "CPV-Code(s)",
  nuts_codes:              "NUTS-Code(s)",
  auftragswert:            "Auftragswert",
  leistungsort:            "Leistungsort",
  laufzeit:                "Laufzeit",
  ansprechpartner:         "Ansprechpartner",
  email:                   "E-Mail",
  telefon:                 "Telefon",
  fax:                     "Fax",
};

function fieldCount(fields: Record<string, any>): number {
  return Object.entries(FIELD_LABELS).filter(([k]) => {
    const v = fields[k];
    return v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);
  }).length;
}

// ── ExtractionCard ────────────────────────────────────────────────────

function ExtractionCard({ record, onReExtract }: { record: any; onReExtract: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [reExtracting, setReExtracting] = useState(false);

  const fields = record.fields ?? {};
  const count = fieldCount(fields);

  async function handleReExtract() {
    setReExtracting(true);
    try {
      await fetch(api(`/extract/${record.job_item_id}/trigger`), { method: "POST" });
      onReExtract(record.job_item_id);
    } finally {
      setReExtracting(false);
    }
  }

  return (
    <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
      {/* Header */}
      <div
        className="flex items-start gap-3 px-5 py-4 cursor-pointer hover:bg-slate-50 transition-colors"
        onClick={() => setOpen(v => !v)}
      >
        <button className="mt-0.5 flex-shrink-0 text-slate-400">
          {open ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>

        <div className="flex-1 min-w-0 space-y-1.5">
          {/* Title row */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 border border-indigo-100 rounded-full text-[10px] font-bold text-indigo-700">
              <CheckCircle2 className="w-3 h-3" />{count} fields
            </span>
            <span className="text-[10px] bg-slate-100 border border-slate-200 text-slate-500 px-2 py-0.5 rounded-full font-mono">
              {record.docs_parsed} doc{record.docs_parsed !== 1 ? "s" : ""}
            </span>
            <span className="text-[10px] text-slate-400 font-mono">{record.runtime_seconds}s</span>
            <span className="text-[10px] text-slate-400">
              {new Date(record.created_at).toLocaleString()}
            </span>
          </div>

          {/* Primary fields inline */}
          <div className="flex flex-wrap gap-x-4 gap-y-0.5">
            {fields.vergabenummer && (
              <span className="text-[10px] text-slate-600"><span className="font-bold">Nr:</span> {fields.vergabenummer}</span>
            )}
            {fields.titel && (
              <span className="text-[10px] text-slate-600 truncate max-w-[40ch]"><span className="font-bold">Titel:</span> {fields.titel}</span>
            )}
            {fields.abgabefrist && (
              <span className="text-[10px] text-slate-600"><span className="font-bold">Frist:</span> {fields.abgabefrist}</span>
            )}
            {fields.auftraggeber && (
              <span className="text-[10px] text-slate-600 truncate max-w-[32ch]"><span className="font-bold">AG:</span> {fields.auftraggeber}</span>
            )}
          </div>

          {/* URL */}
          {record.source_url && (
            <p className="font-mono text-[10px] text-indigo-500 truncate" title={record.source_url}>
              {record.source_url}
            </p>
          )}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-1.5 flex-shrink-0" onClick={e => e.stopPropagation()}>
          <a
            href={api(`/extract/${record.job_item_id}/report?fmt=pdf`)}
            target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1 px-2.5 py-1.5 bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-700 text-[10px] font-bold rounded-lg transition-all"
          >
            <FileOutput className="w-3 h-3" />PDF
          </a>
          <a
            href={api(`/extract/${record.job_item_id}/report?fmt=docx`)}
            target="_blank" rel="noopener noreferrer"
            className="flex items-center gap-1 px-2.5 py-1.5 bg-blue-50 hover:bg-blue-100 border border-blue-200 text-blue-700 text-[10px] font-bold rounded-lg transition-all"
          >
            <FileOutput className="w-3 h-3" />DOCX
          </a>
          <button
            onClick={handleReExtract}
            disabled={reExtracting}
            className="flex items-center gap-1 px-2.5 py-1.5 bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-600 text-[10px] font-bold rounded-lg transition-all disabled:opacity-50"
          >
            {reExtracting ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          </button>
        </div>
      </div>

      {/* Expanded fields */}
      {open && (
        <div className="px-5 pb-5 border-t border-slate-100">
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-px bg-slate-100 rounded-xl overflow-hidden border border-slate-100">
            {Object.entries(FIELD_LABELS).map(([key, label]) => {
              const val = fields[key];
              if (!val || (Array.isArray(val) && val.length === 0)) return null;
              const display = Array.isArray(val) ? val.join(", ") : String(val);
              return (
                <div key={key} className="flex gap-2 px-3 py-2.5 bg-white">
                  <span className="text-[10px] font-bold text-slate-400 w-32 flex-shrink-0 pt-px">{label}</span>
                  <span className="text-[10px] text-slate-700 break-all">{display}</span>
                </div>
              );
            })}
          </div>

          {/* Zuschlagskriterien */}
          {(fields.zuschlagskriterien ?? []).length > 0 && (
            <div className="mt-3 space-y-1">
              <p className="text-[10px] font-bold text-slate-400 uppercase">Zuschlagskriterien</p>
              {fields.zuschlagskriterien.map((c: string, i: number) => (
                <p key={i} className="text-[10px] text-slate-600">• {c}</p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── TriggerPanel — picks from real jobs, no raw UUID required ────────

function TriggerPanel({ onDone }: { onDone: () => void }) {
  const { data: jobs, isLoading: jobsLoading } = useSWR(api("/jobs?limit=50"), fetcher);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [running, setRunning]             = useState(false);
  const [result,  setResult]              = useState<any>(null);
  const [error,   setError]               = useState<string | null>(null);

  // Jobs that have at least one successful item
  const eligibleJobs: any[] = (jobs ?? []).filter(
    (j: any) => j.status === "success" || j.status === "partial" || j.completed > 0
  );

  const selectedJob = eligibleJobs.find((j: any) => j.id === selectedJobId);

  async function handleTrigger() {
    if (!selectedJobId) return;
    setRunning(true); setError(null); setResult(null);
    try {
      const r = await fetch(api(`/extract/job/${selectedJobId}`), { method: "POST" });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body?.detail ?? `HTTP ${r.status}`);
      setResult(body);
      onDone();
    } catch (e: any) {
      setError(e?.message ?? "Unknown error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="bg-white border-2 border-indigo-100 rounded-3xl p-6 shadow-sm space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="p-3 bg-indigo-100/70 border border-indigo-200 rounded-2xl">
          <ScanSearch className="w-5 h-5 text-indigo-700" />
        </div>
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Trigger Deep Extraction</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Select a completed job — all downloaded documents will be parsed and structured fields extracted.
            No AI, no API calls.
          </p>
        </div>
      </div>

      {/* Job selector */}
      <div className="space-y-2">
        <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Select Job</p>
        {jobsLoading ? (
          <div className="flex items-center gap-2 text-sm text-slate-400 py-2">
            <Loader2 className="w-4 h-4 animate-spin" />Loading jobs…
          </div>
        ) : eligibleJobs.length === 0 ? (
          <p className="text-sm text-slate-400 italic py-2">
            No completed jobs found. Run a scraping job first, then come back to extract.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 max-h-56 overflow-y-auto pr-1 custom-scrollbar">
            {eligibleJobs.map((j: any) => (
              <button
                key={j.id}
                onClick={() => setSelectedJobId(j.id === selectedJobId ? "" : j.id)}
                className={`text-left p-3 rounded-xl border transition-all ${
                  j.id === selectedJobId
                    ? "border-indigo-500 bg-indigo-50 ring-1 ring-indigo-400"
                    : "border-slate-200 bg-slate-50 hover:border-slate-300"
                }`}
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <code className="text-[10px] font-mono text-slate-500">{j.id.slice(0, 12)}…</code>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full border ${
                    j.status === "success" ? "bg-emerald-50 text-emerald-700 border-emerald-200" :
                    j.status === "partial"  ? "bg-amber-50 text-amber-700 border-amber-200" :
                    "bg-slate-50 text-slate-500 border-slate-200"
                  }`}>{j.status}</span>
                </div>
                <p className="text-[10px] text-slate-600 font-semibold">
                  {j.completed}/{j.total_urls} URLs · {(j.domains ?? []).slice(0, 2).join(", ")}
                  {(j.domains ?? []).length > 2 ? ` +${j.domains.length - 2}` : ""}
                </p>
                <p className="text-[10px] text-slate-400 mt-0.5">
                  {new Date(j.created_at).toLocaleDateString()}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Selected job info + run button */}
      {selectedJob && (
        <div className="flex items-center justify-between gap-4 pt-2 border-t border-slate-100">
          <div className="text-xs text-slate-600">
            <span className="font-bold">Selected:</span>{" "}
            <code className="font-mono text-indigo-600">{selectedJob.id.slice(0, 16)}…</code>
            {" "}·{" "}{selectedJob.completed} successful URL{selectedJob.completed !== 1 ? "s" : ""}
          </div>
          <button
            onClick={handleTrigger}
            disabled={running}
            className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-bold text-sm rounded-xl transition-all flex-shrink-0"
          >
            {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <ScanSearch className="w-4 h-4" />}
            {running ? "Extracting…" : "Extract All"}
          </button>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-rose-50 border border-rose-200 rounded-xl text-sm text-rose-700">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
        </div>
      )}

      {/* Result summary */}
      {result && (
        <div className={`px-4 py-4 rounded-xl border space-y-3 ${result.extracted > 0 ? "bg-emerald-50 border-emerald-200" : "bg-rose-50 border-rose-200"}`}>
          <div className="flex flex-wrap items-center gap-2">
            <p className={`text-sm font-bold flex items-center gap-1.5 ${result.extracted > 0 ? "text-emerald-800" : "text-rose-700"}`}>
              {result.extracted > 0
                ? <><CheckCircle2 className="w-4 h-4" />Extraction complete</>
                : <><AlertCircle className="w-4 h-4" />Extraction failed</>
              }
            </p>
            {result.extracted > 0 && (
              <span className="text-[10px] font-bold bg-emerald-100 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full">
                {result.extracted} extracted
              </span>
            )}
            {result.failed > 0 && (
              <span className="text-[10px] font-bold bg-rose-100 text-rose-700 border border-rose-200 px-2 py-0.5 rounded-full">
                {result.failed} failed
              </span>
            )}
            {result.live_fetched > 0 && (
              <span className="text-[10px] font-bold bg-indigo-100 text-indigo-700 border border-indigo-200 px-2 py-0.5 rounded-full">
                ⚡ {result.live_fetched} live-fetched
              </span>
            )}
          </div>

          {(result.results ?? []).length > 0 && (
            <div className="space-y-1.5 max-h-52 overflow-y-auto custom-scrollbar">
              {result.results.map((r: any) => (
                <div key={r.job_item_id} className="flex items-start justify-between gap-2 text-[10px] py-1.5 px-2 rounded-lg bg-white/70 border border-emerald-100">
                  <span className="font-mono text-slate-600 truncate max-w-[50ch]" title={r.url}>{r.url || r.job_item_id}</span>
                  <div className="flex items-center gap-1.5 flex-shrink-0">
                    {r.source === "live" && (
                      <span className="text-indigo-600 font-bold bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 rounded">live</span>
                    )}
                    {r.error
                      ? <span className="text-rose-600 font-semibold max-w-[24ch] truncate" title={r.error}>{r.error.slice(0, 60)}</span>
                      : <span className="text-emerald-600 font-semibold">{r.fields_found} fields · {r.docs_parsed} doc{r.docs_parsed !== 1 ? "s" : ""}</span>
                    }
                  </div>
                </div>
              ))}
            </div>
          )}

          {result.extracted > 0 && (
            <div className="flex gap-2 pt-1">
              {result.results.filter((r: any) => !r.error).map((r: any) => (
                <a key={r.job_item_id}
                   href={`/api/backend/extract/${r.job_item_id}/report?fmt=pdf`}
                   target="_blank" rel="noopener noreferrer"
                   className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-600 hover:bg-rose-700 text-white text-xs font-bold rounded-lg"
                >
                  <Download className="w-3.5 h-3.5" />PDF
                </a>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────

export default function ExtractionPage() {
  function handleDone() { /* triggers child refresh via its own mutate */ }

  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
      {/* Header */}
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight flex items-center gap-3">
            <ScanSearch className="w-8 h-8 text-indigo-600" />
            Deep Document Extraction
          </h1>
          <p className="text-slate-500 mt-1.5 text-sm font-medium">
            Structural parsing of downloaded procurement documents — regex field extraction, zero AI or API calls.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-slate-400 bg-slate-50 border border-slate-200 rounded-xl px-4 py-2">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
          <span>Pure code · No LLM · No API</span>
        </div>
      </header>

      {/* Manual trigger panel */}
      <TriggerPanel onDone={handleDone} />

      {/* How it works */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        {[
          { icon: FileText, title: "Parse Documents", desc: "PDF (pdfplumber), DOCX (python-docx), ZIP (recursive) — raw text + tables extracted without any AI." },
          { icon: Layers, title: "Extract Fields", desc: "50+ hand-crafted German procurement regex patterns: Vergabenummer, CPV, Abgabefrist, Auftraggeber, Auftragswert, contacts and more." },
          { icon: Download, title: "Generate Report", desc: "Branded PDF (reportlab) or DOCX (python-docx) with structured field table + full text excerpt. Download instantly." },
        ].map(({ icon: Icon, title, desc }) => (
          <div key={title} className="bg-white border border-slate-200 rounded-2xl p-5 space-y-2 shadow-sm">
            <div className="flex items-center gap-2">
              <Icon className="w-5 h-5 text-indigo-500" />
              <h3 className="font-bold text-slate-800 text-sm">{title}</h3>
            </div>
            <p className="text-xs text-slate-500 leading-relaxed">{desc}</p>
          </div>
        ))}
      </div>

      {/* Extracted records list */}
      <section className="space-y-4">
        <ExtractionRecordsList />
      </section>
    </div>
  );
}

// Fetches all extraction records from the dedicated endpoint
function ExtractionRecordsList() {
  const { data: records, mutate, isLoading } = useSWR(
    api("/extract?limit=200"),
    fetcher,
    { refreshInterval: 15000 }
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold text-slate-800 flex items-center gap-2">
          <CheckCircle2 className="w-5 h-5 text-indigo-500" />
          Extraction Records
        </h2>
        <button
          onClick={() => mutate()}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-all"
        >
          <RefreshCw className="w-3.5 h-3.5" />Refresh
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12 gap-3 text-slate-400">
          <Loader2 className="w-5 h-5 animate-spin text-indigo-500" />
          <span className="text-sm">Loading extraction records…</span>
        </div>
      ) : !records || records.length === 0 ? (
        <div className="text-center py-16 border border-dashed border-slate-200 rounded-2xl bg-white">
          <ScanSearch className="w-10 h-10 text-slate-300 mx-auto mb-3" />
          <p className="text-slate-500 font-semibold text-sm">No extraction records yet</p>
          <p className="text-slate-400 text-xs mt-1">
            Extractions run automatically after each successful scrape, or trigger one manually above.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {records.map((record: any) => (
            <ExtractionCard
              key={record.id}
              record={record}
              onReExtract={() => mutate()}
            />
          ))}
        </div>
      )}
    </div>
  );
}
