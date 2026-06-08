"use client";

import useSWR from "swr";
import { useParams, useRouter } from "next/navigation";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import Link from "next/link";
import {
  Download, FileText, AlertCircle, CheckCircle2, BadgeCheck,
  Loader2, ArrowLeft, Trash2, Copy, Cpu, Clock, DollarSign,
  Layers, Globe, ChevronDown, ChevronRight, RefreshCcw,
  FolderOpen, Shield, HeartPulse, ExternalLink, StopCircle,
  BarChart2, TrendingDown, AlertOctagon, FileDown, Timer,
  ScanSearch, FileOutput, RefreshCw,
} from "lucide-react";
import { useState, useMemo, useEffect, useCallback } from "react";
import { useToast } from "@/components/Toast";

const STRATEGY_STYLES: Record<string, string> = {
  manual_scraper:         "bg-blue-50 text-blue-700 border-blue-200",
  existing_scraper:       "bg-purple-50 text-purple-700 border-purple-200",
  deterministic_template: "bg-emerald-50 text-emerald-700 border-emerald-200",
  llm_generated_scraper:  "bg-amber-50 text-amber-700 border-amber-200",
  computer_use_agent:     "bg-rose-50 text-rose-700 border-rose-200",
  none:                   "bg-slate-50 text-slate-600 border-slate-200",
};
const STRATEGY_LABELS: Record<string, string> = {
  manual_scraper:         "Manual",
  existing_scraper:       "Cached",
  deterministic_template: "Deterministic",
  llm_generated_scraper:  "LLM Generated",
  computer_use_agent:     "CUA Agent",
  none:                   "Failed",
};
// Phase 3 cascade: EXISTING first (reuse) → DETERMINISTIC (free) → LLM → CUA → MANUAL (legacy)
const CASCADE_ORDER = ["existing_scraper","deterministic_template","llm_generated_scraper","computer_use_agent","manual_scraper"];

function fileIcon(fn: string) {
  const e = fn.split(".").pop()?.toLowerCase() ?? "";
  if (e === "pdf") return "📄";
  if (["zip","rar","7z"].includes(e)) return "🗜️";
  if (["doc","docx"].includes(e)) return "📝";
  if (["xls","xlsx"].includes(e)) return "📊";
  return "📎";
}
function fileBadge(e: string) {
  if (e === "pdf") return "bg-rose-50 border-rose-200 text-rose-700";
  if (["zip","rar","7z"].includes(e)) return "bg-amber-50 border-amber-200 text-amber-700";
  if (["doc","docx"].includes(e)) return "bg-blue-50 border-blue-200 text-blue-700";
  if (["xls","xlsx"].includes(e)) return "bg-emerald-50 border-emerald-200 text-emerald-700";
  return "bg-slate-50 border-slate-200 text-slate-600";
}
function fmt(b: number) {
  if (b < 1024) return `${b} B`;
  if (b < 1048576) return `${(b/1024).toFixed(1)} KB`;
  return `${(b/1048576).toFixed(1)} MB`;
}

function StrategyPill({ s, xs }: { s: string; xs?: boolean }) {
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full font-semibold border ${STRATEGY_STYLES[s] ?? STRATEGY_STYLES.none} ${xs ? "text-[10px]" : "text-xs"}`}>
      {STRATEGY_LABELS[s] ?? s.replace(/_/g," ")}
    </span>
  );
}

function CascadeTrail({ item }: { item: any }) {
  const idx = item.strategy === "none" ? -1 : CASCADE_ORDER.indexOf(item.strategy);
  const tried = CASCADE_ORDER.filter((_,i) => item.status==="failed" ? i===0 : i<=idx);
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {tried.map((s,i) => {
        const ok = s===item.strategy && item.status==="success";
        const bad = i===tried.length-1 && item.status==="failed";
        return (
          <div key={s} className="flex items-center gap-1">
            {i>0 && <ChevronRight className="w-3 h-3 text-slate-300" />}
            <span className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${STRATEGY_STYLES[s]} ${!ok&&!bad?"opacity-35":""}`}>
              {ok && <CheckCircle2 className="w-3 h-3" />}
              {bad && <AlertCircle className="w-3 h-3" />}
              {STRATEGY_LABELS[s]}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function ItemErrorBox({ msg }: { msg: string }) {
  if (!msg) return null;
  if (msg.startsWith("[CRITICAL]"))
    return (
      <div className="bg-rose-50 border border-rose-200 p-3 rounded-xl text-xs space-y-1.5">
        <p className="font-bold text-rose-800 flex items-center gap-1.5"><Shield className="w-3.5 h-3.5"/>Security Alert — Pipeline Aborted</p>
        <pre className="text-rose-700 font-mono whitespace-pre-wrap break-all text-[10px]">{msg}</pre>
      </div>
    );
  if (msg.startsWith("[SELF-HEALED]"))
    return (
      <div className="bg-emerald-50 border border-emerald-200 p-3 rounded-xl text-xs space-y-1.5">
        <p className="font-bold text-emerald-800 flex items-center gap-1.5"><HeartPulse className="w-3.5 h-3.5"/>Self-Healed — Auto-recovered</p>
        <pre className="text-emerald-700 font-mono whitespace-pre-wrap break-all text-[10px]">{msg}</pre>
      </div>
    );
  if (msg.startsWith("[CUA-DISCOVERY"))
    return (
      <div className="bg-indigo-50 border border-indigo-200 p-3 rounded-xl text-xs space-y-1.5">
        <p className="font-bold text-indigo-800 flex items-center gap-1.5"><Cpu className="w-3.5 h-3.5"/>CUA Pre-flight Discovery Log</p>
        <pre className="bg-slate-900 text-slate-200 p-2.5 rounded-lg font-mono text-[10px] whitespace-pre-wrap break-all max-h-48 overflow-y-auto custom-scrollbar">
          {msg.replace(/\[CUA-DISCOVERY(-FAILED)?\]\s*/g,"")}
        </pre>
      </div>
    );
  return <div className="bg-rose-50 border border-rose-100 p-2.5 rounded-lg text-[10px] font-mono text-rose-700 break-all">{msg}</div>;
}

// ── Throughput + ETA component ─────────────────────────────────────

function ThroughputBar({ completed, total, status }: { completed: number; total: number; status: string }) {
  const [snapshots, setSnapshots] = useState<{ t: number; c: number }[]>([]);

  // Record snapshots whenever completed changes, to measure URL/min throughput rate.
  // Must be useEffect (not useMemo) because setSnapshots is a side effect.
  useEffect(() => {
    if (status !== "running" && status !== "pending") return;
    const now = Date.now();
    setSnapshots(prev => {
      const updated = [...prev, { t: now, c: completed }];
      return updated.filter(s => now - s.t < 60_000);
    });
  }, [completed, status]);

  if (snapshots.length < 2) {
    return (
      <div className="flex items-center gap-2 text-[10px] text-indigo-500/70">
        <span>Calculating throughput…</span>
      </div>
    );
  }

  const oldest = snapshots[0];
  const newest = snapshots[snapshots.length - 1];
  const deltaURLs = newest.c - oldest.c;
  const deltaMs   = newest.t - oldest.t;
  const ratePerMin = deltaMs > 0 ? Math.round((deltaURLs / deltaMs) * 60_000 * 10) / 10 : 0;
  const remaining  = total - completed;
  const etaSeconds = ratePerMin > 0 ? Math.round((remaining / ratePerMin) * 60) : null;

  const fmtEta = (s: number) => {
    if (s < 60) return `${s}s`;
    if (s < 3600) return `${Math.round(s / 60)}min`;
    return `${(s / 3600).toFixed(1)}h`;
  };

  return (
    <div className="flex flex-wrap items-center gap-4 text-[10px] font-semibold text-indigo-600/80">
      <span>⚡ {ratePerMin} URL/min</span>
      {etaSeconds !== null && <span>⏱ ETA: ~{fmtEta(etaSeconds)}</span>}
      <span className="text-indigo-400">{remaining} remaining</span>
    </div>
  );
}

// ── Attempt Timeline: per-strategy error chain ───────────────────────

const STRATEGY_SHORT: Record<string, string> = {
  manual_scraper:         "Manual",
  existing_scraper:       "Cached",
  deterministic_template: "Deterministic",
  llm_generated_scraper:  "LLM",
  computer_use_agent:     "CUA",
};

// Full 27-category error palette matching backend security.py classify_error()
const ERROR_CAT_COLOR: Record<string, string> = {
  // Infrastructure
  timeout:               "bg-amber-50   text-amber-700   border-amber-200",
  network:               "bg-orange-50  text-orange-700  border-orange-200",
  dns:                   "bg-red-50     text-red-700     border-red-200",
  ssl:                   "bg-red-50     text-red-800     border-red-300",
  redirect_loop:         "bg-yellow-50  text-yellow-700  border-yellow-200",
  encoding_error:        "bg-indigo-50  text-indigo-700  border-indigo-200",
  // Security / validation
  code_validation:       "bg-violet-50  text-violet-700  border-violet-200",
  prompt_injection:      "bg-rose-50    text-rose-800    border-rose-300",
  blocked_url:           "bg-rose-50    text-rose-700    border-rose-200",
  sandbox:               "bg-fuchsia-50 text-fuchsia-700 border-fuchsia-200",
  // Access / auth
  login_required:        "bg-purple-50  text-purple-700  border-purple-200",
  registration_required: "bg-violet-50  text-violet-600  border-violet-200",
  auth:                  "bg-purple-50  text-purple-800  border-purple-300",
  // Bot protection
  captcha:               "bg-orange-50  text-orange-800  border-orange-300",
  // HTTP
  not_found:             "bg-slate-50   text-slate-600   border-slate-200",
  rate_limit:            "bg-yellow-50  text-yellow-700  border-yellow-200",
  server_error:          "bg-rose-50    text-rose-700    border-rose-200",
  // Tender lifecycle
  expired:               "bg-slate-100  text-slate-500   border-slate-300",
  maintenance:           "bg-yellow-50  text-yellow-600  border-yellow-200",
  // Scraper content
  js_required:           "bg-cyan-50    text-cyan-700    border-cyan-200",
  empty_page:            "bg-slate-50   text-slate-400   border-slate-200",
  scraper_crash:         "bg-red-50     text-red-700     border-red-200",
  // Documents / storage
  no_documents:          "bg-blue-50    text-blue-600    border-blue-200",
  storage:               "bg-orange-50  text-orange-700  border-orange-200",
  // Pipeline
  no_strategy:           "bg-slate-50   text-slate-500   border-slate-200",
  loop_exhausted:        "bg-violet-50  text-violet-700  border-violet-200",
  unknown:               "bg-slate-50   text-slate-500   border-slate-200",
};

// Human-readable labels for each category
const ERROR_CAT_LABEL: Record<string, string> = {
  timeout:               "Timeout",
  network:               "Network Error",
  dns:                   "DNS Failure",
  ssl:                   "SSL/TLS Error",
  redirect_loop:         "Redirect Loop",
  encoding_error:        "Encoding Error",
  code_validation:       "Code Invalid",
  prompt_injection:      "Injection Detected",
  blocked_url:           "URL Blocked",
  sandbox:               "Sandbox Limit",
  login_required:        "Login Required",
  registration_required: "Registration Required",
  auth:                  "Auth Denied (401/403)",
  captcha:               "CAPTCHA / Bot Block",
  not_found:             "Not Found (404)",
  rate_limit:            "Rate Limited (429)",
  server_error:          "Server Error (5xx)",
  expired:               "Tender Expired",
  maintenance:           "Site Maintenance",
  js_required:           "JS Required",
  empty_page:            "Empty Page",
  scraper_crash:         "Scraper Crashed",
  no_documents:          "No Documents",
  storage:               "Storage Error",
  no_strategy:           "No Strategy",
  loop_exhausted:        "LLM Loop Exhausted",
  unknown:               "Unknown Error",
};

function AttemptTimeline({ attempts }: { attempts: any[] }) {
  if (!attempts || attempts.length === 0) return null;

  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
        <Timer className="w-3 h-3"/> Strategy Attempt Log
      </p>
      <div className="space-y-1">
        {attempts.map((a: any, i: number) => {
          const catCls = ERROR_CAT_COLOR[a.error_category] ?? ERROR_CAT_COLOR.unknown;
          const shortName = STRATEGY_SHORT[a.strategy] ?? a.strategy;
          const ts = a.timestamp ? new Date(a.timestamp + "Z").toLocaleTimeString() : "";

          return (
            <div key={i} className={`flex items-start gap-2.5 px-3 py-2 rounded-lg border text-[10px] ${
              a.success ? "bg-emerald-50 border-emerald-200" : "bg-white border-slate-100"
            }`}>
              {/* Icon */}
              <span className="flex-shrink-0 mt-0.5">
                {a.success
                  ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500"/>
                  : <AlertCircle  className="w-3.5 h-3.5 text-rose-400"/>}
              </span>

              {/* Strategy name */}
              <span className={`flex-shrink-0 font-bold px-1.5 py-0.5 rounded border ${
                STRATEGY_STYLES[a.strategy] ?? "bg-slate-50 text-slate-600 border-slate-200"
              }`}>
                {shortName}
              </span>

              {/* Result */}
              <div className="flex-1 min-w-0">
                {a.success ? (
                  <span className="text-emerald-700 font-semibold">
                    ✓ Downloaded {a.downloaded} document{a.downloaded !== 1 ? "s" : ""}
                  </span>
                ) : (
                  <div className="space-y-0.5">
                    {/* Human-readable reason */}
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-semibold border ${catCls}`}>
                      {a.error_reason || a.error_raw?.slice(0, 80) || "Unknown error"}
                    </span>
                    {/* Raw technical error (collapsible) */}
                    {a.error_raw && a.error_raw !== a.error_reason && (
                      <p className="font-mono text-slate-400 truncate" title={a.error_raw}>
                        {a.error_raw.slice(0, 120)}{a.error_raw.length > 120 ? "…" : ""}
                      </p>
                    )}
                  </div>
                )}
              </div>

              {/* Duration + timestamp */}
              <div className="flex-shrink-0 text-right text-slate-400 space-y-0.5">
                {a.duration_s > 0 && <p className="font-mono">{a.duration_s}s</p>}
                {ts && <p>{ts}</p>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Deep Extraction result panel — vergabepilot.ai tender card style ──

function fmtDate(s: string | null | undefined): string | null {
  if (!s) return null;
  return s.replace(/(\d{4})-(\d{2})-(\d{2}).*/, "$3.$2.$1") || s;
}

function ExtractionPanel({ result, itemId }: { result: any; itemId: string }) {
  const [showAll, setShowAll] = useState(false);
  const f = result?.fields ?? {};

  const titel       = f.titel || f.vergabenummer || null;
  const authority   = f.auftraggeber || f.vergabestelle || null;
  const pubDate     = fmtDate(f.veroeffentlichungsdatum);
  const deadline    = fmtDate(f.abgabefrist);
  const summary     = f.zusammenfassung || f.leistungsbeschreibung || null;
  const bullets     = (f.kernpunkte ?? []) as string[];
  const value       = f.auftragswert ? `${f.auftragswert}${f.waehrung ? " " + f.waehrung : " EUR"}` : null;
  const procedure   = f.vergabeverfahren || null;
  const contractType= f.auftragsart || null;
  const location    = f.leistungsort || null;
  const cpv         = (f.cpv_codes ?? []).slice(0, 3) as string[];
  const criteria    = (f.zuschlagskriterien ?? []) as string[];
  const eligibility = (f.eignungskriterien ?? []) as string[];

  const isDeadlineUrgent = (() => {
    if (!f.abgabefrist) return false;
    const d = new Date(f.abgabefrist.split(".").reverse().join("-"));
    const diff = (d.getTime() - Date.now()) / (1000 * 60 * 60 * 24);
    return !isNaN(diff) && diff >= 0 && diff <= 14;
  })();

  return (
    <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden shadow-sm">

      {/* Tender card body */}
      <div className="p-4 space-y-2.5">

        {/* Title */}
        {titel && (
          <h4 className="text-sm font-bold text-slate-900 leading-snug">{titel}</h4>
        )}

        {/* Authority */}
        {authority && (
          <p className="text-xs text-slate-600 flex items-center gap-1">
            <span className="text-slate-400">🏛</span> {authority}
          </p>
        )}

        {/* Dates — vergabepilot.ai inline style */}
        {(pubDate || deadline) && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            {pubDate && (
              <span>Veröffentlicht: <span className="font-semibold text-slate-700">{pubDate}</span></span>
            )}
            {pubDate && deadline && <span className="text-slate-300">|</span>}
            {deadline && (
              <span>
                Angebotsfrist:{" "}
                <span className={`font-semibold ${isDeadlineUrgent ? "text-rose-600" : "text-slate-700"}`}>
                  {deadline}
                </span>
                {isDeadlineUrgent && (
                  <span className="ml-1 text-[9px] font-bold text-white bg-rose-500 rounded px-1 py-0.5">Bald</span>
                )}
              </span>
            )}
          </div>
        )}

        {/* Summary */}
        {summary && (
          <p className="text-xs text-slate-600 leading-relaxed border-l-2 border-indigo-200 pl-3">
            {summary}
          </p>
        )}

        {/* Key bullets (top 3) */}
        {bullets.length > 0 && !summary && (
          <ul className="space-y-0.5">
            {bullets.slice(0, 3).map((b, i) => (
              <li key={i} className="flex gap-1.5 text-xs text-slate-600">
                <span className="text-indigo-400 flex-shrink-0">•</span><span>{b}</span>
              </li>
            ))}
          </ul>
        )}

        {/* Tags */}
        <div className="flex flex-wrap gap-1.5 pt-0.5">
          {procedure && (
            <span className="px-2 py-0.5 text-[10px] font-semibold rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">{procedure}</span>
          )}
          {contractType && (
            <span className="px-2 py-0.5 text-[10px] font-semibold rounded-full bg-slate-100 text-slate-600 border border-slate-200">{contractType}</span>
          )}
          {value && (
            <span className="px-2 py-0.5 text-[10px] font-semibold rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">€ {value}</span>
          )}
          {location && (
            <span className="px-2 py-0.5 text-[10px] font-semibold rounded-full bg-amber-50 text-amber-700 border border-amber-200">📍 {location}</span>
          )}
          {cpv.map(c => (
            <span key={c} className="px-2 py-0.5 text-[10px] font-mono rounded-full bg-slate-50 text-slate-500 border border-slate-200">{c}</span>
          ))}
        </div>
      </div>

      {/* Action bar */}
      <div className="px-4 py-2.5 border-t border-slate-100 bg-slate-50/60 flex flex-wrap items-center gap-2">
        <a href={api(`/extract/${itemId}/report?fmt=pdf`)} target="_blank" rel="noopener noreferrer"
           className="flex items-center gap-1 px-2.5 py-1.5 bg-rose-50 hover:bg-rose-100 border border-rose-200 text-rose-700 text-[10px] font-bold rounded-lg transition-all">
          <FileOutput className="w-3 h-3"/>PDF
        </a>
        <a href={api(`/extract/${itemId}/report?fmt=docx`)} target="_blank" rel="noopener noreferrer"
           className="flex items-center gap-1 px-2.5 py-1.5 bg-blue-50 hover:bg-blue-100 border border-blue-200 text-blue-700 text-[10px] font-bold rounded-lg transition-all">
          <FileOutput className="w-3 h-3"/>DOCX
        </a>
        <button onClick={() => setShowAll(v => !v)}
                className="flex items-center gap-1 px-2.5 py-1.5 bg-white border border-slate-200 text-slate-600 text-[10px] font-semibold rounded-lg hover:bg-slate-100 transition-all ml-auto">
          {showAll ? <ChevronDown className="w-3 h-3"/> : <ChevronRight className="w-3 h-3"/>}
          Alle Felder
        </button>
        <span className="text-[10px] text-slate-400 font-mono">
          {result.docs_parsed} Dok. · {result.runtime_seconds}s
        </span>
      </div>

      {/* Expanded full fields */}
      {showAll && (
        <div className="px-4 pb-4 pt-2 border-t border-slate-100 space-y-3">
          {/* Full bullets */}
          {bullets.length > 0 && (
            <ul className="space-y-0.5">
              {bullets.map((b, i) => (
                <li key={i} className="flex gap-1.5 text-[10px] text-slate-600">
                  <span className="text-indigo-400 flex-shrink-0">•</span><span>{b}</span>
                </li>
              ))}
            </ul>
          )}
          {/* Field grid */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-px bg-slate-100 rounded-xl overflow-hidden border border-slate-100">
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
            ] as [string, string | null][]).map(([label, val]) => {
              if (!val) return null;
              return (
                <div key={label} className="flex gap-2 px-3 py-2 bg-white">
                  <span className="text-[10px] font-bold text-slate-400 w-28 flex-shrink-0 pt-px">{label}</span>
                  <span className="text-[10px] text-slate-700 break-all">{val}</span>
                </div>
              );
            })}
          </div>
          {/* Criteria */}
          {criteria.length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-slate-400 uppercase mb-1">Zuschlagskriterien</p>
              {criteria.map((c, i) => <p key={i} className="text-[10px] text-slate-600">• {c}</p>)}
            </div>
          )}
          {eligibility.length > 0 && (
            <div>
              <p className="text-[10px] font-bold text-slate-400 uppercase mb-1">Eignungskriterien</p>
              {eligibility.map((c, i) => <p key={i} className="text-[10px] text-slate-600">• {c}</p>)}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function URLRow({ item, docs, onRetry, retrying }: { item: any; docs: any[]; onRetry:(id:string)=>void; retrying:boolean }) {
  const [open, setOpen] = useState(false);
  const [extracting,       setExtracting]       = useState(false);
  const [extractionResult, setExtractionResult] = useState<any>(null);
  const [extractionChecked, setExtractionChecked] = useState(false);

  // Auto-load existing extraction result when row is expanded and has docs
  useEffect(() => {
    if (!open || docs.length === 0 || extractionChecked) return;
    setExtractionChecked(true);
    fetch(api(`/extract/${item.id}`))
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setExtractionResult(data); })
      .catch(() => {});
  }, [open, docs.length, extractionChecked, item.id]);

  async function handleExtract() {
    setExtracting(true);
    try {
      const r = await fetch(api(`/extract/${item.id}/trigger`), { method: "POST" });
      if (r.ok) setExtractionResult(await r.json());
    } catch { /* silent */ }
    finally { setExtracting(false); }
  }

  // Build a short failure summary from attempts_detail if error_message is generic
  const failureSummary = useMemo(() => {
    const attempts: any[] = item.attempts_detail ?? [];
    if (item.status !== "failed" || attempts.length === 0) return null;
    const last = [...attempts].reverse().find((a: any) => !a.success);
    if (!last) return null;
    return last.error_reason || last.error_raw?.slice(0, 100) || null;
  }, [item]);

  return (
    <div className="border border-slate-100 rounded-xl overflow-hidden">
      {/* Header row */}
      <div
        className="flex items-start gap-3 px-4 py-3 bg-slate-50 hover:bg-slate-100 transition-colors cursor-pointer"
        onClick={() => setOpen(v => !v)}
      >
        <button className="mt-0.5 flex-shrink-0 text-slate-400">
          {open ? <ChevronDown className="w-4 h-4"/> : <ChevronRight className="w-4 h-4"/>}
        </button>

        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-1.5 mb-1">
            <StatusBadge status={item.status}/>
            <StrategyPill s={item.strategy}/>
            {docs.length > 0 && (
              <span className="text-[10px] font-bold bg-emerald-100 text-emerald-700 border border-emerald-200 px-2 py-0.5 rounded-full">
                {docs.length} file{docs.length !== 1 ? "s" : ""}
              </span>
            )}
            <span className="text-[10px] text-slate-400 font-mono">
              {item.runtime_seconds?.toFixed(1)}s
              {item.iterations > 0 && ` · ${item.iterations} iter${item.iterations !== 1 ? "s" : ""}`}
            </span>
          </div>

          {/* URL */}
          <p className="font-mono text-[10px] text-indigo-700 break-all" title={item.url}>{item.url}</p>

          {/* failure_category badge + inline reason (collapsed view) */}
          {item.status === "failed" && (
            <div className="flex flex-wrap items-center gap-1.5 mt-1">
              {item.failure_category && item.failure_category !== "unknown" && (
                <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${ERROR_CAT_COLOR[item.failure_category] ?? ERROR_CAT_COLOR.unknown}`}>
                  {ERROR_CAT_LABEL[item.failure_category] ?? item.failure_category.replace(/_/g, " ")}
                </span>
              )}
              {failureSummary && !open && (
                <span className="text-[10px] text-rose-500 truncate" title={failureSummary}>
                  {failureSummary.slice(0, 100)}{failureSummary.length > 100 ? "…" : ""}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-1.5 flex-shrink-0">
          {item.status === "failed" && (
            <button
              onClick={e => { e.stopPropagation(); onRetry(item.id); }}
              disabled={retrying}
              className="flex items-center gap-1 px-2.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-[10px] font-bold rounded-lg transition-all disabled:opacity-50"
            >
              {retrying ? <Loader2 className="w-3 h-3 animate-spin"/> : <RefreshCcw className="w-3 h-3"/>}Retry
            </button>
          )}
          <a
            href={item.url} target="_blank" rel="noopener noreferrer"
            onClick={e => e.stopPropagation()}
            className="p-1.5 text-slate-400 hover:text-indigo-600 transition-colors"
          >
            <ExternalLink className="w-3.5 h-3.5"/>
          </a>
        </div>
      </div>

      {/* Expanded panel */}
      {open && (
        <div className="px-4 pb-4 pt-3 border-t border-slate-100 space-y-4">
          {/* Strategy cascade visual */}
          <CascadeTrail item={item}/>

          {/* Full attempt timeline with per-strategy error reasons */}
          {(item.attempts_detail?.length ?? 0) > 0
            ? <AttemptTimeline attempts={item.attempts_detail}/>
            : item.error_message && <ItemErrorBox msg={item.error_message}/>
          }

          {/* Downloaded documents */}
          {docs.length > 0 ? (
            <div className="space-y-1.5">
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Downloaded Documents</p>
              {docs.map((doc: any) => {
                const ext = doc.filename.split(".").pop()?.toLowerCase() ?? "";
                const verified = ["pdf","zip","docx","xlsx","doc","xls","ppt","pptx","rar","7z"].includes(ext);
                return (
                  <div key={doc.id} className="flex items-center justify-between py-2 px-3 bg-white border border-slate-100 rounded-lg">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className={`text-base p-1.5 rounded-lg border flex-shrink-0 ${fileBadge(ext)}`}>
                        {fileIcon(doc.filename)}
                      </span>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="text-xs font-semibold text-slate-800 truncate max-w-[22ch]" title={doc.filename}>
                            {doc.filename}
                          </p>
                          {verified
                            ? <BadgeCheck className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0"/>
                            : <AlertCircle className="w-3.5 h-3.5 text-amber-400 flex-shrink-0"/>}
                        </div>
                        <p className="text-[10px] text-slate-400">{fmt(doc.size_bytes)} · v{doc.version}</p>
                      </div>
                    </div>
                    {doc.download_url
                      ? <a href={api(doc.download_url)} download={doc.filename}
                           className="flex items-center gap-1 px-2.5 py-1.5 bg-slate-100 hover:bg-slate-200 border border-slate-200 text-xs font-semibold rounded-lg transition-all ml-3 flex-shrink-0">
                          <Download className="w-3 h-3"/>Download
                        </a>
                      : <span className="text-[10px] text-slate-400 ml-3">Unavailable</span>}
                  </div>
                );
              })}
            </div>
          ) : (
            item.status !== "running" && item.status !== "pending" && (
              <p className="text-xs text-slate-400 italic">No documents downloaded for this URL.</p>
            )
          )}

          {/* Deep Document Extraction */}
          {docs.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5">
                  <ScanSearch className="w-3 h-3"/>Deep Document Analysis
                </p>
                <button
                  onClick={handleExtract}
                  disabled={extracting}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white text-[10px] font-bold rounded-lg transition-all"
                >
                  {extracting
                    ? <><Loader2 className="w-3 h-3 animate-spin"/>Extracting…</>
                    : extractionResult
                      ? <><RefreshCw className="w-3 h-3"/>Re-extract</>
                      : <><ScanSearch className="w-3 h-3"/>Extract Fields</>
                  }
                </button>
              </div>

              {!extractionResult && !extracting && (
                <p className="text-[10px] text-slate-400 italic">
                  Click &quot;Extract Fields&quot; to deep-parse documents and generate a structured report (no AI, pure text analysis).
                </p>
              )}

              {extracting && (
                <div className="flex items-center gap-2 px-3 py-3 border border-indigo-100 rounded-xl bg-indigo-50/40">
                  <Loader2 className="w-4 h-4 animate-spin text-indigo-500"/>
                  <span className="text-xs text-indigo-600 font-medium">Parsing documents and extracting procurement fields…</span>
                </div>
              )}

              {extractionResult && !extracting && (
                <ExtractionPanel result={extractionResult} itemId={item.id}/>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function DomainSection({ domain, items, docsByItem, onRetry, retryingId }: {
  domain:string; items:any[]; docsByItem:Record<string,any[]>; onRetry:(id:string)=>void; retryingId:string|null;
}) {
  const [open, setOpen] = useState(true);
  const totalDocs = items.reduce((acc,i)=>acc+(docsByItem[i.id]?.length??0),0);
  const ok = items.filter(i=>i.status==="success").length;
  return (
    <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
      <button onClick={()=>setOpen(v=>!v)} className="w-full flex items-center gap-3 px-5 py-3.5 bg-slate-50 hover:bg-slate-100 transition-colors text-left">
        {open?<ChevronDown className="w-4 h-4 text-slate-500"/>:<ChevronRight className="w-4 h-4 text-slate-500"/>}
        <Globe className="w-4 h-4 text-indigo-500 flex-shrink-0"/>
        <span className="font-bold text-slate-800 text-sm truncate">{domain}</span>
        <div className="flex items-center gap-2 ml-2 flex-shrink-0">
          <span className="text-[10px] bg-indigo-50 text-indigo-700 border border-indigo-100 px-2 py-0.5 rounded-full font-bold">{items.length} URL{items.length!==1?"s":""}</span>
          <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold border ${ok===items.length?"bg-emerald-50 text-emerald-700 border-emerald-100":"bg-amber-50 text-amber-700 border-amber-100"}`}>{ok}/{items.length} OK</span>
          {totalDocs>0 && <span className="text-[10px] bg-slate-100 text-slate-600 border border-slate-200 px-2 py-0.5 rounded-full font-bold">{totalDocs} doc{totalDocs!==1?"s":""}</span>}
        </div>
      </button>
      {open && (
        <div className="px-5 py-4 space-y-2 border-t border-slate-100">
          {items.map(item=>(
            <URLRow key={item.id} item={item} docs={docsByItem[item.id]??[]} onRetry={onRetry} retrying={retryingId===item.id}/>
          ))}
        </div>
      )}
    </div>
  );
}

export default function JobDetailPage() {
  const { id }    = useParams<{ id: string }>();
  const router    = useRouter();
  const toast     = useToast();
  const [isZipping,    setIsZipping]    = useState(false);
  const [isDeleting,   setIsDeleting]   = useState(false);
  const [isStopping,   setIsStopping]   = useState(false);
  const [retryingId,   setRetryingId]   = useState<string|null>(null);
  const [copied,       setCopied]       = useState(false);
  const [showDiag,     setShowDiag]     = useState(false);
  const [diag,         setDiag]         = useState<any|null>(null);
  const [diagLoading,  setDiagLoading]  = useState(false);

  const { data: job, mutate: mutateJob } = useSWR(id?api(`/jobs/${id}`):null, fetcher, {
    refreshInterval: d=>(!d||d.status==="pending"||d.status==="running")?2000:0,
  });
  const { data: documents, mutate: mutateDocs } = useSWR(id?api(`/jobs/${id}/documents`):null, fetcher, {
    refreshInterval: ()=>(job?.status==="pending"||job?.status==="running")?2000:0,
  });

  const docsByItem = useMemo<Record<string,any[]>>(()=>{
    const m:Record<string,any[]>={};
    for (const d of documents??[]) { const k=d.job_item_id??"__x__"; if(!m[k])m[k]=[]; m[k].push(d); }
    return m;
  },[documents]);

  const byDomain = useMemo<Record<string,any[]>>(()=>{
    const m:Record<string,any[]>={};
    for (const i of job?.items??[]) { const k=i.domain||"unknown"; if(!m[k])m[k]=[]; m[k].push(i); }
    return m;
  },[job]);

  const domains  = Object.keys(byDomain).sort();
  const totalDocs= documents?.length??0;
  const pct      = job?Math.max(4,Math.round((job.completed/Math.max(1,job.total_urls))*100)):0;

  // All hooks must be declared before any conditional return (rules-of-hooks)
  const handleZip = useCallback(async () => {
    if (isZipping) return;
    setIsZipping(true);
    try {
      const r = await fetch(api(`/jobs/${id}/download-all`));
      if (!r.ok) throw new Error(r.statusText);
      const url = URL.createObjectURL(await r.blob());
      const a   = document.createElement("a");
      a.href     = url;
      a.download = `job-${id?.slice(0, 8)}-docs.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      toast.error("ZIP download failed", e?.message);
    } finally {
      setIsZipping(false);
    }
  }, [id, isZipping, toast]);

  const handleDelete = useCallback(async () => {
    if (!window.confirm("Delete job permanently?")) return;
    setIsDeleting(true);
    try {
      const r = await fetch(api(`/jobs/${id}`), { method: "DELETE" });
      if (!r.ok) throw new Error(r.statusText);
      router.push("/jobs");
    } catch (e: any) {
      toast.error("Delete failed", e?.message);
      setIsDeleting(false);
    }
  }, [id, router, toast]);

  const handleStop = useCallback(async () => {
    if (!window.confirm("Stop this job? All pending URLs will be marked as failed.")) return;
    setIsStopping(true);
    try {
      const r = await fetch(api(`/jobs/${id}/stop`), { method: "POST" });
      if (!r.ok) throw new Error(r.statusText);
      mutateJob();
    } catch (e: any) {
      toast.error("Stop failed", e?.message);
    } finally {
      setIsStopping(false);
    }
  }, [id, mutateJob, toast]);

  const handleDiagnostics = useCallback(async () => {
    setShowDiag(true);
    setDiagLoading(true);
    try {
      const r = await fetch(api(`/jobs/${id}/diagnostics`));
      setDiag(r.ok ? await r.json() : null);
    } catch {
      setDiag(null);
    } finally {
      setDiagLoading(false);
    }
  }, [id]);

  const handleRetry = useCallback(async (itemId: string) => {
    setRetryingId(itemId);
    try {
      const r = await fetch(api(`/jobs/${id}/items/${itemId}/retry`), { method: "POST" });
      if (!r.ok) throw new Error(r.statusText);
      setTimeout(() => { mutateJob(); mutateDocs(); setRetryingId(null); }, 1500);
    } catch (e: any) {
      setRetryingId(null);
      toast.error("Retry failed", e?.message);
    }
  }, [id, mutateJob, mutateDocs, toast]);
  const copyId = useCallback(() => {
    navigator.clipboard.writeText(job?.id ?? "");
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [job?.id]);

  // Guard: show spinner while job data loads (placed after all hooks)
  if (!job) return (
    <div className="max-w-7xl mx-auto px-4 py-16 text-center">
      <Loader2 className="w-6 h-6 animate-spin text-indigo-600 mx-auto mb-3"/>
      <p className="text-slate-500 text-sm">Loading job…</p>
    </div>
  );

  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs font-medium text-slate-500">
        <Link href="/" className="hover:text-indigo-600">Dashboard</Link><span>/</span>
        <Link href="/jobs" className="flex items-center gap-1 hover:text-indigo-600"><ArrowLeft className="w-3 h-3"/>Jobs</Link><span>/</span>
        <span className="text-slate-400 truncate max-w-[16ch]">{job.id.slice(0,8)}</span>
      </div>

      {/* Header */}
      <header className="space-y-3 border-b border-slate-100 pb-5">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <code className="font-mono text-sm bg-slate-100 border border-slate-200 px-4 py-2 rounded-xl text-slate-700">{job.id}</code>
            <button onClick={copyId} className="btn-secondary text-xs gap-1.5"><Copy className="w-3.5 h-3.5"/>{copied?"Copied!":"Copy"}</button>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Link href={`/audit?job=${id}`} className="btn-secondary text-xs gap-1.5">
              <Layers className="w-3.5 h-3.5"/>Audit Trail
            </Link>
            <button onClick={handleDiagnostics} className="btn-secondary text-xs gap-1.5">
              <BarChart2 className="w-3.5 h-3.5"/>Diagnostics
            </button>
            <a
              href={api(`/jobs/${id}/error-report?fmt=csv`)}
              download={`error-report-${id?.slice(0,8)}.csv`}
              className="btn-secondary text-xs gap-1.5"
              title="Download full error report as CSV"
            >
              <FileDown className="w-3.5 h-3.5"/>Error Report
            </a>
            {(job.status==="running"||job.status==="pending") && (
              <button onClick={handleStop} disabled={isStopping} className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-50 hover:bg-amber-100 border border-amber-300 text-amber-800 text-xs font-semibold rounded-lg transition-all disabled:opacity-50">
                {isStopping?<Loader2 className="w-3.5 h-3.5 animate-spin"/>:<StopCircle className="w-3.5 h-3.5"/>}
                {isStopping?"Stopping…":"Stop Job"}
              </button>
            )}
            <button onClick={handleDelete} disabled={isDeleting} className="btn-danger text-xs gap-1.5">
              <Trash2 className="w-3.5 h-3.5"/>{isDeleting?"Deleting…":"Delete"}
            </button>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={job.status}/>
          {[
            [Layers, `${job.completed}/${job.total_urls} URLs`],
            [FileText, `${totalDocs} docs`],
            [Globe, `${domains.length} domain${domains.length!==1?"s":""}`],
            [DollarSign, `$${(job.cost_usd??0).toFixed(4)}`],
            [Clock, new Date(job.created_at).toLocaleString()],
          ].map(([Icon,label]:any,i)=>(
            <span key={i} className="badge bg-slate-100 text-slate-600 border-slate-200">
              <Icon className="w-3 h-3 mr-1"/>{label}
            </span>
          ))}
        </div>
      </header>

      {/* Progress */}
      {(job.status==="pending"||job.status==="running")&&(
        <div className="p-4 border border-indigo-100 bg-indigo-50/40 rounded-2xl space-y-3">
          {/* Progress bar */}
          <div className="flex justify-between text-xs font-semibold text-indigo-700">
            <span className="flex items-center gap-1.5">
              <Loader2 className="w-3.5 h-3.5 animate-spin"/>Pipeline running…
            </span>
            <span>{pct}% ({job.completed}/{job.total_urls})</span>
          </div>
          <div className="w-full bg-indigo-100 rounded-full h-2.5 overflow-hidden">
            <div className="bg-indigo-600 h-2.5 rounded-full transition-all duration-700" style={{width:`${pct}%`}}/>
          </div>
          {/* Throughput + ETA */}
          <ThroughputBar completed={job.completed} total={job.total_urls} status={job.status}/>
        </div>
      )}

      {/* Failure Category Breakdown — shown when job has failed items */}
      {(() => {
        const failedItems = job.items?.filter((i: any) => i.status === "failed") ?? [];
        if (failedItems.length === 0) return null;
        const catCounts: Record<string, number> = {};
        for (const i of failedItems) {
          const cat = i.failure_category || "unknown";
          catCounts[cat] = (catCounts[cat] || 0) + 1;
        }
        const sorted = Object.entries(catCounts).sort((a, b) => b[1] - a[1]);
        return (
          <section className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
            <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
              <AlertOctagon className="w-4 h-4 text-rose-500"/>
              <h2 className="font-bold text-slate-800 text-sm">Failure Breakdown <span className="font-normal text-slate-400">({failedItems.length} failed URL{failedItems.length !== 1 ? "s" : ""})</span></h2>
            </div>
            <div className="px-5 py-4 flex flex-wrap gap-2">
              {sorted.map(([cat, count]) => (
                <div key={cat} className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full border font-semibold text-xs ${ERROR_CAT_COLOR[cat] ?? ERROR_CAT_COLOR.unknown}`}>
                  <span>{ERROR_CAT_LABEL[cat] ?? cat.replace(/_/g, " ")}</span>
                  <span className="bg-white/60 px-1.5 py-0.5 rounded-full text-[10px] font-bold">{count}</span>
                </div>
              ))}
            </div>
          </section>
        );
      })()}

      {/* Domain → URL → Docs tree */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold text-slate-800 flex items-center gap-2">
            <FolderOpen className="w-5 h-5 text-indigo-600"/>URLs by Domain
          </h2>
          {totalDocs>0&&(
            <button onClick={handleZip} disabled={isZipping} className="btn-primary text-xs gap-1.5 disabled:opacity-60">
              {isZipping?<><Loader2 className="w-3.5 h-3.5 animate-spin"/>Zipping…</>:<><Download className="w-3.5 h-3.5"/>Download All ZIP</>}
            </button>
          )}
        </div>
        {domains.length===0
          ? <div className="text-center py-12 text-slate-400 text-sm border border-slate-200 rounded-2xl bg-white">No URL items.</div>
          : domains.map(d=>(
            <DomainSection key={d} domain={d} items={byDomain[d]} docsByItem={docsByItem} onRetry={handleRetry} retryingId={retryingId}/>
          ))
        }
      </section>

      {/* Compact run-history table */}
      <section className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 bg-slate-50">
          <h2 className="font-bold text-slate-800 text-sm">Cascade Run History</h2>
        </div>
        <div className="overflow-x-auto max-h-72 custom-scrollbar">
          <table className="w-full text-xs">
            <thead className="bg-slate-50 border-b border-slate-100 sticky top-0">
              <tr>
                {["URL","Strategy","Iters","Time","Docs","Failure Reason","Status"].map(h=>(
                  <th key={h} className={`px-5 py-3 font-semibold text-slate-500 uppercase tracking-wide ${h==="Status"?"text-right":h==="URL"?"text-left":"text-center"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {job.items?.map((item:any)=>(
                <tr key={item.id} className="hover:bg-slate-50/50 transition-colors">
                  <td className="px-5 py-3 font-mono text-[10px] text-slate-600 max-w-[24ch] truncate" title={item.url}>{item.url}</td>
                  <td className="px-5 py-3"><StrategyPill s={item.strategy} xs/></td>
                  <td className="px-5 py-3 text-center font-semibold text-slate-600">{item.iterations}</td>
                  <td className="px-5 py-3 text-center font-mono text-slate-500">{item.runtime_seconds?.toFixed(1)}s</td>
                  <td className="px-5 py-3 text-center font-bold text-slate-700">{item.document_count}</td>
                  <td className="px-5 py-3 text-center">
                    {item.failure_category && item.failure_category !== "unknown"
                      ? <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold border ${ERROR_CAT_COLOR[item.failure_category] ?? ERROR_CAT_COLOR.unknown}`}>
                          {ERROR_CAT_LABEL[item.failure_category] ?? item.failure_category}
                        </span>
                      : <span className="text-slate-300">—</span>}
                  </td>
                  <td className="px-5 py-3 text-right"><StatusBadge status={item.status}/></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* ── Pipeline Diagnostics Modal ── */}
      {showDiag && (
        <div className="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/60 backdrop-blur-sm overflow-y-auto py-8 px-4" onClick={e=>{if(e.target===e.currentTarget)setShowDiag(false);}}>
          <div className="bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-3xl">
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100">
              <h2 className="font-bold text-slate-800 flex items-center gap-2">
                <BarChart2 className="w-5 h-5 text-indigo-600"/>Pipeline Diagnostics
              </h2>
              <button onClick={()=>setShowDiag(false)} className="p-1.5 rounded-lg text-slate-400 hover:bg-slate-100 transition-colors">✕</button>
            </div>

            <div className="p-6 space-y-6 max-h-[80vh] overflow-y-auto custom-scrollbar">
              {diagLoading && (
                <div className="flex items-center justify-center py-12 gap-3 text-slate-400">
                  <Loader2 className="w-5 h-5 animate-spin text-indigo-600"/>
                  <span className="text-sm">Loading diagnostics…</span>
                </div>
              )}

              {!diagLoading && diag && (
                <>
                  {/* Summary strip */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                    {[
                      {label:"Succeeded", value:diag.succeeded, color:"text-emerald-600"},
                      {label:"Failed",    value:diag.failed,    color:"text-rose-600"},
                      {label:"Pending",   value:diag.pending,   color:"text-amber-600"},
                      {label:"Cost",      value:`$${diag.cost_usd}`, color:"text-slate-700"},
                    ].map(({label,value,color})=>(
                      <div key={label} className="bg-slate-50 border border-slate-200 rounded-xl p-3 text-center">
                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-0.5">{label}</p>
                        <p className={`text-xl font-extrabold ${color}`}>{value}</p>
                      </div>
                    ))}
                  </div>

                  {/* Error category breakdown */}
                  {Object.keys(diag.error_category_breakdown||{}).length>0 && (
                    <div>
                      <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                        <TrendingDown className="w-3.5 h-3.5 text-rose-500"/>Failure Reasons
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(diag.error_category_breakdown).sort((a:any,b:any)=>b[1]-a[1]).map(([cat,count]:any)=>(
                          <span key={cat} className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-50 border border-rose-200 text-rose-700 rounded-full text-xs font-bold">
                            <AlertOctagon className="w-3 h-3"/>{cat} <span className="bg-rose-200 text-rose-800 px-1.5 rounded-full text-[10px]">{count}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Per-domain results */}
                  <div>
                    <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2 flex items-center gap-1.5">
                      <Globe className="w-3.5 h-3.5 text-indigo-500"/>Domain Results
                    </p>
                    <div className="space-y-2">
                      {Object.entries(diag.domain_results||{}).map(([domain,data]:any)=>{
                        const failedUrls=data.urls.filter((u:any)=>u.status==="failed");
                        return (
                          <div key={domain} className="border border-slate-200 rounded-xl overflow-hidden">
                            <div className="flex items-center gap-3 px-4 py-2.5 bg-slate-50">
                              <Globe className="w-3.5 h-3.5 text-indigo-500 flex-shrink-0"/>
                              <span className="text-xs font-bold text-slate-700 truncate flex-1">{domain}</span>
                              <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full">{data.urls.filter((u:any)=>u.status==="success").length} ✓</span>
                              <span className="text-[10px] font-bold text-rose-600 bg-rose-50 border border-rose-200 px-2 py-0.5 rounded-full">{failedUrls.length} ✗</span>
                            </div>
                            {failedUrls.length>0 && (
                              <div className="divide-y divide-slate-100">
                                {failedUrls.map((u:any,i:number)=>(
                                  <div key={i} className="px-4 py-2 text-[10px] space-y-1">
                                    <p className="font-mono text-indigo-700 truncate">{u.url}</p>
                                    <div className="flex flex-wrap items-center gap-2 text-slate-500">
                                      <span className="font-semibold">{u.strategy?.replace(/_/g," ")||"none"}</span>
                                      <span>·</span>
                                      <span>{u.iterations} iters</span>
                                      <span>·</span>
                                      <span>{u.runtime_seconds}s</span>
                                      <span>·</span>
                                      <span className="text-rose-600 font-medium">{u.error?.slice(0,120)||"unknown error"}</span>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Audit trail */}
                  {diag.audit_trail?.length>0 && (
                    <div>
                      <p className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-2">Audit Trail ({diag.audit_trail.length} events)</p>
                      <div className="bg-slate-950 rounded-xl p-3 max-h-48 overflow-y-auto custom-scrollbar space-y-1">
                        {diag.audit_trail.map((e:any,i:number)=>(
                          <div key={i} className="flex items-start gap-2 text-[10px] font-mono">
                            <span className={`flex-shrink-0 font-bold ${e.level==="critical"?"text-rose-400":e.level==="error"?"text-orange-400":e.level==="warning"?"text-amber-400":"text-slate-400"}`}>{e.level.toUpperCase()}</span>
                            <span className="text-slate-500 flex-shrink-0">{new Date(e.time).toLocaleTimeString()}</span>
                            <span className="text-indigo-300 flex-shrink-0">{e.event}</span>
                            <span className="text-slate-300 truncate">{e.message}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}

              {!diagLoading && !diag && (
                <div className="text-center py-8 text-slate-400 text-sm">Failed to load diagnostics. Check that the API is running.</div>
              )}
            </div>

            <div className="px-6 py-4 border-t border-slate-100 flex justify-between items-center">
              <Link href={`/audit?job=${id}`} className="text-xs text-indigo-600 hover:underline font-semibold">
                View full audit log →
              </Link>
              <button onClick={()=>setShowDiag(false)} className="btn-secondary text-xs">Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
