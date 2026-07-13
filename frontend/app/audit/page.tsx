/**
 * Audit Log page — append-only structured event history of all pipeline activity.
 *
 * Every significant action the pipeline takes (job start, strategy attempt,
 * success/failure, security event, manual stop) is written to the audit_logs
 * table and surfaces here so ops can reconstruct exactly what happened for
 * any job, URL, or incident.
 *
 * Features:
 *   - Filterable table: by level (info/warning/error/critical), event type, domain
 *   - URL and job_id deep-link from each row to the relevant job detail page
 *   - Purge control: delete audit entries older than N days
 *   - Live refresh: new events appear automatically
 *
 * Data source:
 *   GET /api/audit          → paginated log entries (newest first)
 *   DELETE /api/audit/purge → remove entries older than ?days=N
 *
 * Level color coding:
 *   info → blue  |  warning → amber  |  error → rose  |  critical → red (bold)
 */
"use client";

import useSWR from "swr";
import { useState, useMemo, useEffect, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import {
  ShieldAlert, Info, AlertTriangle, XCircle,
  Search, RefreshCcw, Trash2, ChevronDown, ChevronRight,
  Activity, Clock, Filter,
} from "lucide-react";
import { SearchInput, SectionHeader } from "@/components/ui";
import { useToast } from "@/components/Toast";

const LEVEL_STYLES: Record<string, string> = {
  info:     "bg-slate-100 text-slate-600 border-slate-200",
  warning:  "bg-amber-50 text-amber-700 border-amber-200",
  error:    "bg-orange-50 text-orange-700 border-orange-200",
  critical: "bg-rose-50 text-rose-700 border-rose-200",
};
const LEVEL_ICONS: Record<string, any> = {
  info:     Info,
  warning:  AlertTriangle,
  error:    XCircle,
  critical: ShieldAlert,
};

function LevelBadge({ level }: { level: string }) {
  const cls = LEVEL_STYLES[level] ?? LEVEL_STYLES.info;
  const Icon = LEVEL_ICONS[level] ?? Info;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold border ${cls}`}>
      <Icon className="w-3 h-3" />{level}
    </span>
  );
}

function AuditRow({ log }: { log: any }) {
  const [open, setOpen] = useState(false);
  const hasExtra = Object.keys(log.extra ?? {}).length > 0;

  return (
    <div className={`border-b border-slate-100 ${log.level === "critical" ? "bg-rose-50/30" : log.level === "error" ? "bg-orange-50/20" : ""}`}>
      <div
        className="flex items-start gap-3 px-5 py-3 hover:bg-slate-50/50 transition-colors cursor-pointer"
        onClick={() => hasExtra && setOpen(v => !v)}
      >
        <span className="text-[10px] font-mono text-slate-400 w-36 flex-shrink-0 pt-0.5">
          {new Date(log.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
          <br />
          <span className="text-slate-300">{new Date(log.created_at).toLocaleDateString()}</span>
        </span>

        <div className="flex-1 min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <LevelBadge level={log.level} />
            <code className="text-[10px] font-mono bg-slate-100 text-slate-600 px-2 py-0.5 rounded">
              {log.event_type}
            </code>
            {log.domain && (
              <span className="text-[10px] text-indigo-600 font-semibold">{log.domain}</span>
            )}
            {log.strategy && (
              <span className="text-[10px] text-purple-600 font-semibold bg-purple-50 px-1.5 py-0.5 rounded border border-purple-100">
                {log.strategy}
              </span>
            )}
          </div>
          <p className="text-xs text-slate-700 leading-snug">{log.message}</p>
          {log.url && (
            <p className="font-mono text-[10px] text-slate-400 truncate" title={log.url}>{log.url}</p>
          )}
        </div>

        {log.job_id && (
          <Link
            href={`/jobs/${log.job_id}`}
            onClick={e => e.stopPropagation()}
            className="flex-shrink-0 text-[10px] font-mono text-indigo-600 hover:underline"
          >
            {log.job_id.slice(0, 8)}
          </Link>
        )}

        {hasExtra && (
          <button className="flex-shrink-0 text-slate-400 hover:text-slate-600">
            {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
          </button>
        )}
      </div>

      {open && hasExtra && (
        <div className="mx-5 mb-3 bg-slate-900 rounded-xl p-3 text-[10px] font-mono text-slate-200 overflow-x-auto custom-scrollbar">
          <pre>{JSON.stringify(log.extra, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}

function AuditPageInner() {
  const searchParams  = useSearchParams();
  const [search,      setSearch]      = useState("");
  const [levelFilter, setLevelFilter] = useState("");
  // Initialise jobFilter from ?job= query param (linked from job detail page)
  const [jobFilter,   setJobFilter]   = useState(() => searchParams.get("job") ?? "");
  const [clearing,    setClearing]    = useState(false);
  const toast = useToast();

  // Keep jobFilter in sync if the URL param changes (browser back/forward)
  useEffect(() => {
    const p = searchParams.get("job");
    if (p) setJobFilter(p);
  }, [searchParams]);

  const queryStr = new URLSearchParams({
    limit: "200",
    ...(levelFilter ? { level: levelFilter } : {}),
    ...(jobFilter   ? { job_id: jobFilter } : {}),
  }).toString();

  const { data: logs, isLoading, mutate } = useSWR(
    api(`/audit?${queryStr}`), fetcher, { refreshInterval: 6000 }
  );
  const { data: stats } = useSWR(api("/audit/stats"), fetcher, { refreshInterval: 15000 });

  const filtered = useMemo(() => {
    if (!logs) return [];
    if (!search) return logs;
    const q = search.toLowerCase();
    return logs.filter((l: any) =>
      l.message?.toLowerCase().includes(q) ||
      l.event_type?.toLowerCase().includes(q) ||
      l.domain?.toLowerCase().includes(q) ||
      l.url?.toLowerCase().includes(q)
    );
  }, [logs, search]);

  const handleClear = async () => {
    if (!window.confirm("Purge all audit logs? This cannot be undone.")) return;
    setClearing(true);
    try {
      const r = await fetch(api("/audit"), { method: "DELETE" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      mutate([]);
      toast.success("Audit log cleared");
    } catch (e: any) {
      toast.error("Failed to clear audit log", e?.message);
    } finally {
      setClearing(false);
    }
  };

  const levels = ["", "info", "warning", "error", "critical"];

  return (
    <div className="space-y-6">
      <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Audit Log
          </h1>
          <p className="text-slate-500 mt-1 text-sm">Structured event trail for every pipeline operation, security event, and system action.</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => mutate()} className="btn-secondary text-xs gap-1.5">
            <RefreshCcw className="w-3.5 h-3.5" /> Refresh
          </button>
          <button onClick={handleClear} disabled={clearing} className="btn-danger text-xs gap-1.5">
            <Trash2 className="w-3.5 h-3.5" /> {clearing ? "Clearing…" : "Clear All"}
          </button>
        </div>
      </header>

      {/* Stats strip */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Total Events", value: stats.total, color: "text-slate-700" },
            { label: "Warnings",     value: stats.by_level?.warning ?? 0, color: "text-amber-600" },
            { label: "Errors",       value: stats.by_level?.error   ?? 0, color: "text-orange-600" },
            { label: "Critical",     value: stats.by_level?.critical ?? 0, color: "text-rose-600" },
          ].map(({ label, value, color }) => (
            <div key={label} className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm text-center">
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">{label}</p>
              <p className={`text-2xl font-extrabold ${color}`}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col md:flex-row gap-3 bg-slate-50 p-3 rounded-xl border border-slate-200">
        <div className="relative flex-1 self-start">
          <div className="absolute inset-y-0 left-3 flex items-center pointer-events-none">
            <Search className="w-4 h-4 text-slate-400" />
          </div>
          <input
            type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search message, event type, domain, URL…"
            className="form-input pl-9"
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          <select value={levelFilter} onChange={e=>setLevelFilter(e.target.value)} className="form-select w-36">
            <option value="">All Levels</option>
            {["info","warning","error","critical"].map(l=><option key={l} value={l}>{l}</option>)}
          </select>
          <input
            type="text" value={jobFilter} onChange={e=>setJobFilter(e.target.value)}
            placeholder="Job ID filter…"
            className="form-input w-44"
          />
          {(levelFilter||jobFilter) && (
            <button onClick={()=>{setLevelFilter("");setJobFilter("");}} className="btn-secondary text-xs gap-1">
              <Filter className="w-3 h-3"/>Clear
            </button>
          )}
        </div>
      </div>

      {/* Log table */}
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100 bg-slate-50 flex items-center justify-between">
          <p className="text-xs font-semibold text-slate-500">
            {isLoading ? "Loading…" : `${filtered.length} event${filtered.length !== 1 ? "s" : ""}`}
          </p>
          <span className="flex items-center gap-1.5 text-[10px] text-slate-400">
            <Clock className="w-3 h-3" /> Auto-refreshes every 6s
          </span>
        </div>

        <div className="max-h-[600px] overflow-y-auto custom-scrollbar">
          {isLoading && (
            <div className="py-12 text-center text-slate-400 text-sm">Loading audit events…</div>
          )}
          {!isLoading && filtered.length === 0 && (
            <div className="py-12 text-center text-slate-400 text-sm">
              No audit events match your filters.
            </div>
          )}
          {filtered.map((log: any) => <AuditRow key={log.id} log={log} />)}
        </div>
      </div>
    </div>
  );
}

// Suspense boundary required by Next.js 14 when useSearchParams is used
export default function AuditPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center min-h-[40vh] text-sm" style={{ color: "var(--fg-subtle)" }}>
        Loading audit log…
      </div>
    }>
      <AuditPageInner />
    </Suspense>
  );
}
