/**
 * Extraction page — view and trigger deep extraction of tender fields.
 *
 * After documents are downloaded, the DeepExtractor parses them (PDF/DOCX/XML)
 * and extracts structured fields: Vergabenummer, Auftraggeber, CPV codes,
 * deadlines, contract value, etc. This page surfaces those results.
 *
 * Features:
 *   - List of extraction records (one per successfully scraped job item)
 *   - Field detail panel: all extracted TenderFields in a readable layout
 *   - Download report: generates a PDF or DOCX from the extracted fields
 *   - Re-trigger extraction: re-run the extractor on already-downloaded documents
 *
 * Data sources:
 *   GET  /api/extract              → all extraction records (newest first)
 *   GET  /api/extract/{item_id}    → fields for a specific job item
 *   GET  /api/extract/{item_id}/report?fmt=pdf  → download PDF report
 *   POST /api/extract/{item_id}/trigger         → re-run extraction
 */
"use client";

import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useState } from "react";
import {
  ScanSearch, FileOutput, Loader2, RefreshCw, AlertCircle,
  ExternalLink, Download, Building2, Calendar, Euro,
  MapPin, Tag, ChevronDown, ChevronRight,
} from "lucide-react";

// ── Helpers ────────────────────────────────────────────────────────────

function fmtDate(s: string | null | undefined): string | null {
  if (!s) return null;
  return s.replace(/(\d{4})-(\d{2})-(\d{2}).*/, "$3.$2.$1") || s;
}

function fieldCount(fields: Record<string, any>): number {
  const counted = [
    "vergabenummer","ted_reference","auftraggeber","vergabestelle","titel",
    "leistungsbeschreibung","vergabeverfahren","auftragsart","veroeffentlichungsdatum",
    "abgabefrist","bindefrist","cpv_codes","nuts_codes","auftragswert",
    "waehrung","leistungsort","laufzeit","ansprechpartner","email","telefon","fax",
  ];
  return counted.filter(k => {
    const v = fields[k];
    return v !== null && v !== undefined && v !== "" && !(Array.isArray(v) && v.length === 0);
  }).length;
}

// ── TenderCard ─────────────────────────────────────────────────────────
// Matches vergabepilot.ai layout: title → authority → dates → summary → tags → actions

function TenderCard({ record, onReExtract }: { record: any; onReExtract: () => void }) {
  const [detailOpen, setDetailOpen] = useState(false);
  const [reExtracting, setReExtracting] = useState(false);

  const f = record.fields ?? {};
  const count = fieldCount(f);

  const titel       = f.titel || f.vergabenummer || "Ausschreibung";
  const authority   = f.auftraggeber || f.vergabestelle || null;
  const pubDate     = fmtDate(f.veroeffentlichungsdatum);
  const deadline    = fmtDate(f.abgabefrist);
  const summary     = f.zusammenfassung || f.leistungsbeschreibung || null;
  const bullets     = (f.kernpunkte ?? []) as string[];
  const value       = f.auftragswert ? `${f.auftragswert}${f.waehrung ? " " + f.waehrung : " EUR"}` : null;
  const location    = f.leistungsort || null;
  const procedure   = f.vergabeverfahren || null;
  const contractType= f.auftragsart || null;
  const cpv         = (f.cpv_codes ?? []).slice(0, 3) as string[];
  const criteria    = (f.zuschlagskriterien ?? []) as string[];
  const eligibility = (f.eignungskriterien ?? []) as string[];
  const lots        = (f.lose ?? []) as string[];

  async function handleReExtract() {
    setReExtracting(true);
    try {
      await fetch(api(`/extract/${record.job_item_id}/trigger`), { method: "POST" });
      onReExtract();
    } finally {
      setReExtracting(false);
    }
  }

  const isDeadlineUrgent = (() => {
    if (!f.abgabefrist) return false;
    const d = new Date(f.abgabefrist.split(".").reverse().join("-"));
    const diff = (d.getTime() - Date.now()) / (1000 * 60 * 60 * 24);
    return !isNaN(diff) && diff >= 0 && diff <= 14;
  })();

  return (
    <article className="card overflow-hidden transition-shadow hover:shadow-md">

      {/* ── Card body ───────────────────────────────────────────────── */}
      <div className="p-5 sm:p-6 space-y-4">

        {/* Title + deadline chip */}
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-base sm:text-lg font-bold leading-snug min-w-0" style={{ color: "var(--fg)" }}>
            {titel}
          </h3>
          {deadline && (
            <span
              className={`badge flex-shrink-0 ${isDeadlineUrgent
                ? "bg-rose-50 text-rose-700 border-rose-200"
                : "bg-slate-100 text-slate-600 border-slate-200"}`}
              title="Angebotsfrist"
            >
              <Calendar className="w-3 h-3" />
              {deadline}{isDeadlineUrgent && " · bald"}
            </span>
          )}
        </div>

        {/* Authority + publication date */}
        {(authority || pubDate) && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" style={{ color: "var(--fg-muted)" }}>
            {authority && (
              <span className="flex items-center gap-1.5 min-w-0">
                <Building2 className="w-3.5 h-3.5 flex-shrink-0" style={{ color: "var(--fg-subtle)" }} />
                <span className="truncate">{authority}</span>
              </span>
            )}
            {pubDate && (
              <span className="flex items-center gap-1.5" style={{ color: "var(--fg-subtle)" }}>
                <Calendar className="w-3.5 h-3.5" />Veröffentlicht: {pubDate}
              </span>
            )}
          </div>
        )}

        {/* Summary */}
        {summary && (
          <p className="text-sm leading-relaxed pl-3" style={{ color: "var(--fg-muted)", borderLeft: "2px solid var(--brand)" }}>
            {summary}
          </p>
        )}

        {/* Bullets (shown when there is no summary) */}
        {bullets.length > 0 && !summary && (
          <ul className="space-y-1">
            {bullets.slice(0, 4).map((b, i) => (
              <li key={i} className="flex gap-2 text-sm" style={{ color: "var(--fg-muted)" }}>
                <span className="flex-shrink-0" style={{ color: "var(--brand)" }}>•</span>
                <span>{b}</span>
              </li>
            ))}
          </ul>
        )}

        {/* Tags: procedure, type, value, location, CPV */}
        {(procedure || contractType || value || location || cpv.length > 0) && (
          <div className="flex flex-wrap gap-1.5 pt-0.5">
            {procedure && <span className="badge bg-indigo-50 text-indigo-700 border-indigo-200">{procedure}</span>}
            {contractType && <span className="badge bg-slate-100 text-slate-600 border-slate-200">{contractType}</span>}
            {value && <span className="badge bg-emerald-50 text-emerald-700 border-emerald-200"><Euro className="w-3 h-3" />{value}</span>}
            {location && <span className="badge bg-amber-50 text-amber-700 border-amber-200"><MapPin className="w-3 h-3" />{location}</span>}
            {cpv.map((c) => (
              <span key={c} className="badge bg-slate-50 text-slate-500 border-slate-200 font-mono"><Tag className="w-3 h-3" />{c}</span>
            ))}
          </div>
        )}
      </div>

      {/* ── Action bar ─────────────────────────────────────────────── */}
      <div className="px-5 sm:px-6 py-3 flex flex-wrap items-center gap-2"
           style={{ borderTop: "1px solid var(--border)", background: "var(--bg-subtle)" }}>

        {record.source_url && (
          <a href={record.source_url} target="_blank" rel="noopener noreferrer" className="btn-primary btn-sm">
            <ExternalLink className="w-3.5 h-3.5" />Zur Ausschreibung
          </a>
        )}

        <a href={api(`/extract/${record.job_item_id}/report?fmt=pdf`)} target="_blank" rel="noopener noreferrer" className="btn-secondary btn-sm">
          <FileOutput className="w-3.5 h-3.5" />PDF
        </a>
        <a href={api(`/extract/${record.job_item_id}/report?fmt=docx`)} target="_blank" rel="noopener noreferrer" className="btn-secondary btn-sm">
          <FileOutput className="w-3.5 h-3.5" />DOCX
        </a>

        <button onClick={handleReExtract} disabled={reExtracting} className="btn-ghost btn-sm ml-auto"
                title="Erneut extrahieren" aria-label="Erneut extrahieren">
          {reExtracting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
        </button>

        <button onClick={() => setDetailOpen(v => !v)} className="btn-secondary btn-sm" aria-expanded={detailOpen}>
          {detailOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          {count} Felder
        </button>
      </div>

      {/* ── Expanded full detail ────────────────────────────────────── */}
      {detailOpen && (
        <div className="px-5 sm:px-6 pb-5 pt-4 space-y-5" style={{ borderTop: "1px solid var(--border)" }}>

          {/* Full bullet list */}
          {bullets.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: "var(--fg-subtle)" }}>Kernpunkte</p>
              <ul className="space-y-1">
                {bullets.map((b, i) => (
                  <li key={i} className="flex gap-2 text-sm" style={{ color: "var(--fg-muted)" }}>
                    <span className="flex-shrink-0" style={{ color: "var(--brand)" }}>•</span>
                    <span>{b}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* All extracted fields */}
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-3 rounded-xl p-4" style={{ background: "var(--bg-subtle)" }}>
            {([
              ["Vergabenummer", f.vergabenummer],
              ["TED-Referenz", f.ted_reference],
              ["Auftraggeber", f.auftraggeber],
              ["Vergabestelle", f.vergabestelle],
              ["Vergabeverfahren", f.vergabeverfahren],
              ["Auftragsart", f.auftragsart],
              ["Veröffentlicht", fmtDate(f.veroeffentlichungsdatum)],
              ["Abgabefrist", fmtDate(f.abgabefrist)],
              ["Bindefrist", f.bindefrist],
              ["Auftragswert", f.auftragswert ? `${f.auftragswert} ${f.waehrung || "EUR"}` : null],
              ["Leistungsort", f.leistungsort],
              ["Laufzeit", f.laufzeit],
              ["CPV-Code(s)", (f.cpv_codes ?? []).join(", ")],
              ["NUTS-Code(s)", (f.nuts_codes ?? []).join(", ")],
              ["Ansprechpartner", f.ansprechpartner],
              ["E-Mail", f.email],
              ["Telefon", f.telefon],
              ["Fax", f.fax],
            ] as [string, string | null][]).map(([label, val]) => {
              if (!val) return null;
              return (
                <div key={label} className="flex flex-col gap-0.5">
                  <dt className="text-[10px] font-bold uppercase tracking-wide" style={{ color: "var(--fg-subtle)" }}>{label}</dt>
                  <dd className="text-sm break-words" style={{ color: "var(--fg)" }}>{val}</dd>
                </div>
              );
            })}
          </dl>

          {/* Leistungsbeschreibung */}
          {f.leistungsbeschreibung && (
            <div className="space-y-1.5">
              <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: "var(--fg-subtle)" }}>Leistungsbeschreibung</p>
              <p className="text-sm leading-relaxed" style={{ color: "var(--fg-muted)" }}>{f.leistungsbeschreibung}</p>
            </div>
          )}

          {/* Zuschlagskriterien */}
          {criteria.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: "var(--fg-subtle)" }}>Zuschlagskriterien</p>
              <ul className="space-y-1">
                {criteria.map((c, i) => (
                  <li key={i} className="flex gap-2 text-sm" style={{ color: "var(--fg-muted)" }}><span className="flex-shrink-0" style={{ color: "var(--brand)" }}>•</span><span>{c}</span></li>
                ))}
              </ul>
            </div>
          )}

          {/* Eignungskriterien */}
          {eligibility.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: "var(--fg-subtle)" }}>Eignungskriterien</p>
              <ul className="space-y-1">
                {eligibility.map((c, i) => (
                  <li key={i} className="flex gap-2 text-sm" style={{ color: "var(--fg-muted)" }}><span className="flex-shrink-0" style={{ color: "var(--brand)" }}>•</span><span>{c}</span></li>
                ))}
              </ul>
            </div>
          )}

          {/* Lose */}
          {lots.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-[11px] font-bold uppercase tracking-wide" style={{ color: "var(--fg-subtle)" }}>Lose / Teillose</p>
              <ul className="space-y-1">
                {lots.map((l, i) => (
                  <li key={i} className="flex gap-2 text-sm" style={{ color: "var(--fg-muted)" }}><span className="flex-shrink-0" style={{ color: "var(--brand)" }}>•</span><span>{l}</span></li>
                ))}
              </ul>
            </div>
          )}

          {/* Meta */}
          <p className="text-[11px] pt-1" style={{ color: "var(--fg-subtle)" }}>
            {record.docs_parsed} Dokument{record.docs_parsed !== 1 ? "e" : ""} geparst · {record.runtime_seconds}s · {new Date(record.created_at).toLocaleString("de-DE")}
          </p>
        </div>
      )}
    </article>
  );
}

// ── TriggerPanel ────────────────────────────────────────────────────────

function TriggerPanel({ onDone }: { onDone: () => void }) {
  const { data: jobs, isLoading: jobsLoading } = useSWR(api("/jobs?limit=50"), fetcher);
  const [selectedJobId, setSelectedJobId] = useState("");
  const [running, setRunning]             = useState(false);
  const [result,  setResult]              = useState<any>(null);
  const [error,   setError]               = useState<string | null>(null);

  const eligibleJobs: any[] = (jobs ?? []).filter(
    (j: any) => j.status === "success" || j.status === "partial" || j.completed > 0
  );
  const selectedJob = eligibleJobs.find((j: any) => j.id === selectedJobId);

  async function handleTrigger() {
    if (!selectedJobId) return;
    setRunning(true); setError(null); setResult(null);
    try {
      // Dispatch background task — returns immediately with task_id
      const r = await fetch(api(`/extract/job/${selectedJobId}`), { method: "POST" });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(body?.detail ?? `HTTP ${r.status}`);

      const taskId: string = body.task_id;
      // Poll until done (every 3s, no browser timeout issues)
      while (true) {
        await new Promise(res => setTimeout(res, 3000));
        const poll = await fetch(api(`/extract/task/${taskId}`));
        const status = await poll.json().catch(() => ({}));
        if (status.status === "done") {
          setResult(status.result);
          onDone();
          break;
        }
        if (status.status === "failed") {
          throw new Error(status.error ?? "Extraction task failed");
        }
        // still running / pending — keep polling
      }
    } catch (e: any) {
      setError(e?.message ?? "Unknown error");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="card p-5 sm:p-6 space-y-5">
      <div className="flex items-center gap-3">
        <div className="p-3 bg-indigo-100/70 border border-indigo-200 rounded-2xl">
          <ScanSearch className="w-5 h-5 text-indigo-700" />
        </div>
        <div>
          <h2 className="text-lg font-extrabold text-slate-900">Extraktion starten</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Wählen Sie einen abgeschlossenen Job — alle Dokumente werden geparst und strukturierte Felder extrahiert.
            Deterministisch · Kein LLM · Kostenlos.
          </p>
        </div>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-bold text-slate-500 uppercase tracking-wider">Job auswählen</p>
        {jobsLoading ? (
          <div className="flex items-center gap-2 text-sm text-slate-400 py-2">
            <Loader2 className="w-4 h-4 animate-spin" />Lädt…
          </div>
        ) : eligibleJobs.length === 0 ? (
          <p className="text-sm text-slate-400 italic py-2">
            Keine abgeschlossenen Jobs gefunden. Zuerst einen Scraping-Job starten.
          </p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 max-h-56 overflow-y-auto pr-1">
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
                  {new Date(j.created_at).toLocaleDateString("de-DE")}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>

      {selectedJob && (
        <div className="flex items-center justify-between gap-4 pt-2 border-t border-slate-100">
          <div className="text-xs text-slate-600">
            <span className="font-bold">Ausgewählt:</span>{" "}
            <code className="font-mono text-indigo-600">{selectedJob.id.slice(0, 16)}…</code>
            {" "}·{" "}{selectedJob.completed} URL{selectedJob.completed !== 1 ? "s" : ""}
          </div>
          <button
            onClick={handleTrigger}
            disabled={running}
            className="flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white font-bold text-sm rounded-xl transition-all flex-shrink-0"
          >
            {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <ScanSearch className="w-4 h-4" />}
            {running ? "Extrahiere…" : "Alle extrahieren"}
          </button>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 px-4 py-3 bg-rose-50 border border-rose-200 rounded-xl text-sm text-rose-700">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />{error}
        </div>
      )}

      {result && (
        <div className={`px-4 py-4 rounded-xl border space-y-3 ${result.extracted > 0 ? "bg-emerald-50 border-emerald-200" : "bg-rose-50 border-rose-200"}`}>
          <div className="flex flex-wrap items-center gap-2">
            <p className={`text-sm font-bold ${result.extracted > 0 ? "text-emerald-800" : "text-rose-700"}`}>
              {result.extracted > 0 ? `✓ ${result.extracted} Ausschreibungen extrahiert` : "Extraktion fehlgeschlagen"}
            </p>
            {result.failed > 0 && (
              <span className="text-[10px] font-bold bg-rose-100 text-rose-700 border border-rose-200 px-2 py-0.5 rounded-full">
                {result.failed} fehlgeschlagen
              </span>
            )}
            {result.live_fetched > 0 && (
              <span className="text-[10px] font-bold bg-indigo-100 text-indigo-700 border border-indigo-200 px-2 py-0.5 rounded-full">
                ⚡ {result.live_fetched} live abgerufen
              </span>
            )}
          </div>
          {result.extracted > 0 && (
            <div className="flex flex-wrap gap-2 pt-1">
              {result.results.filter((r: any) => !r.error).slice(0, 5).map((r: any) => (
                <a key={r.job_item_id}
                   href={api(`/extract/${r.job_item_id}/report?fmt=pdf`)}
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

// ── Extraction Records List ─────────────────────────────────────────────

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
          <ScanSearch className="w-5 h-5 text-indigo-500" />
          Extrahierte Ausschreibungen
          {records && (
            <span className="text-xs font-normal text-slate-400 ml-1">({records.length})</span>
          )}
        </h2>
        <button
          onClick={() => mutate()}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-slate-600 bg-white border border-slate-200 rounded-lg hover:bg-slate-50 transition-all"
        >
          <RefreshCw className="w-3.5 h-3.5" />Aktualisieren
        </button>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-12 gap-3 text-slate-400">
          <Loader2 className="w-5 h-5 animate-spin text-indigo-500" />
          <span className="text-sm">Lade Ausschreibungen…</span>
        </div>
      ) : !records || records.length === 0 ? (
        <div className="card text-center py-16 px-6" style={{ borderStyle: "dashed" }}>
          <ScanSearch className="w-10 h-10 mx-auto mb-3" style={{ color: "var(--fg-subtle)" }} />
          <p className="font-semibold text-sm" style={{ color: "var(--fg)" }}>Noch keine extrahierten Ausschreibungen</p>
          <p className="text-xs mt-1" style={{ color: "var(--fg-muted)" }}>
            Extraktion läuft automatisch nach jedem erfolgreichen Scraping-Job, oder manuell oben starten.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {records.map((record: any) => (
            <TenderCard
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

// ── Main page ───────────────────────────────────────────────────────────

export default function ExtractionPage() {
  const { mutate } = useSWR(api("/extract?limit=200"), fetcher, { revalidateOnMount: false });

  return (
    <div className="space-y-8 max-w-5xl mx-auto">

      {/* Header */}
      <header className="section-header">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ color: "var(--fg)" }}>
            Ausschreibungsanalyse
          </h1>
          <p className="mt-1.5 text-sm sm:text-base font-medium" style={{ color: "var(--fg-muted)" }}>
            Strukturierte Datenextraktion aus heruntergeladenen Vergabedokumenten — deterministisch, ohne KI, kostenlos.
          </p>
        </div>
      </header>

      {/* Trigger panel */}
      <TriggerPanel onDone={() => mutate()} />

      {/* Records */}
      <ExtractionRecordsList />
    </div>
  );
}
