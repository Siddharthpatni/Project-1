/**
 * System Admin page — ops dashboard for infrastructure health and error triage.
 *
 * Panels:
 *   - System health check: live status of DB, Redis, MinIO, OpenRouter, Celery workers
 *   - Recent errors: failed URL items with error category, severity, and domain
 *   - Circuit breakers: per-domain CB state (open = fast-failing that domain)
 *   - Danger zone: reset-DB and reset-stale-jobs controls
 *
 * Data sources:
 *   GET /api/admin/system-check    → live ping of all infrastructure components
 *   GET /api/admin/errors          → most recent failed URL items (default 50)
 *   GET /api/admin/circuit-breakers → per-domain circuit breaker state
 *   POST /api/admin/reset          → wipe all data (requires confirmation)
 *   POST /api/admin/reset-stale-jobs → mark stuck RUNNING/PENDING jobs as FAILED
 */
"use client";

import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import Link from "next/link";
import {
  AlertTriangle,
  Activity,
  Database,
  RefreshCcw,
  ShieldAlert,
  ShieldCheck,
  Clock,
  Globe,
  Layers,
  ChevronDown,
  ChevronRight,
  Filter,
  XCircle,
  Trash2,
} from "lucide-react";
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  PieChart,
  Pie,
} from "recharts";
import { useState } from "react";
import { useToast } from "@/components/Toast";

// Severity → visual style
const SEVERITY_STYLES: Record<string, { bg: string; text: string; border: string; dot: string }> = {
  critical: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", dot: "bg-rose-500" },
  error:    { bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-200", dot: "bg-orange-500" },
  warning:  { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200", dot: "bg-amber-500" },
  info:     { bg: "bg-slate-50", text: "text-slate-600", border: "border-slate-200", dot: "bg-slate-400" },
};

// Error category → colors for the pie/bar chart — covers all 27 backend categories
const CATEGORY_COLORS: Record<string, string> = {
  // Infrastructure
  timeout:               "#f59e0b",
  network:               "#f97316",
  dns:                   "#dc2626",
  ssl:                   "#b91c1c",
  redirect_loop:         "#fbbf24",
  encoding_error:        "#6366f1",
  // Security / validation
  code_validation:       "#7c3aed",
  prompt_injection:      "#e11d48",
  blocked_url:           "#be123c",
  sandbox:               "#a21caf",
  // Access / auth
  login_required:        "#9333ea",
  registration_required: "#7e22ce",
  auth:                  "#d97706",
  // Bot protection
  captcha:               "#ea580c",
  // HTTP
  not_found:             "#6b7280",
  rate_limit:            "#f97316",
  server_error:          "#ef4444",
  // Tender lifecycle
  expired:               "#94a3b8",
  maintenance:           "#ca8a04",
  // Scraper content
  js_required:           "#0891b2",
  empty_page:            "#cbd5e1",
  scraper_crash:         "#dc2626",
  // Documents / storage
  no_documents:          "#64748b",
  storage:               "#ea580c",
  // Pipeline
  no_strategy:           "#94a3b8",
  loop_exhausted:        "#ca8a04",
  unknown:               "#9ca3af",
};

export default function AdminPage() {
  const toast = useToast();
  const { data: stats, error: statsError, isLoading: statsLoading, mutate: mutateStats } = useSWR(api("/admin/stats"), fetcher, { refreshInterval: 10000 });
  const { data: errors, error: errorsError, isLoading: errorsLoading, mutate: mutateErrors } = useSWR(api("/admin/errors"), fetcher, { refreshInterval: 10000 });
  const { data: needsManual } = useSWR(api("/jobs/needs-manual"), fetcher, { refreshInterval: 15000 });
  const [filterCategory, setFilterCategory] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const [resetConfirm, setResetConfirm] = useState("");
  const [isResetting, setIsResetting] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);

  const [isResettingJobs, setIsResettingJobs] = useState(false);
  const [resetJobsSuccess, setResetJobsSuccess] = useState(false);

  const [systemCheck, setSystemCheck] = useState<any | null>(null);
  const [isChecking, setIsChecking] = useState(false);
  const [checkError, setCheckError] = useState<string | null>(null);
  const [activeModalService, setActiveModalService] = useState<any | null>(null);

  const handleSystemCheck = async () => {
    setIsChecking(true);
    setCheckError(null);
    try {
      const res = await fetch(api("/admin/system-check"));
      if (res.ok) {
        const data = await res.json();
        setSystemCheck(data);
      } else {
        setCheckError("Failed to fetch system integrity diagnostic report.");
      }
    } catch (err) {
      setCheckError("Network error while running system diagnostic check.");
    } finally {
      setIsChecking(false);
    }
  };

  const isRefreshing = statsLoading || errorsLoading;

  const handleReset = async () => {
    if (resetConfirm.toLowerCase() !== "reset") return;
    setIsResetting(true);
    try {
      const res = await fetch(api("/admin/reset"), { method: "POST" });
      if (res.ok) {
        setResetSuccess(true);
        setResetConfirm("");
        mutateStats();
        mutateErrors();
        setTimeout(() => setResetSuccess(false), 5000);
      } else {
        toast.error("Reset failed");
      }
    } catch (err) {
      toast.error("Error during reset");
    } finally {
      setIsResetting(false);
    }
  };

  const handleResetStaleJobs = async () => {
    setIsResettingJobs(true);
    try {
      const res = await fetch(api("/admin/reset-stale-jobs"), { method: "POST" });
      if (res.ok) {
        setResetJobsSuccess(true);
        mutateStats();
        mutateErrors();
        setTimeout(() => setResetJobsSuccess(false), 5000);
      } else {
        toast.error("Failed to reset stale jobs");
      }
    } catch (err) {
      toast.error("Error resetting stale jobs");
    } finally {
      setIsResettingJobs(false);
    }
  };

  const baseErrors = errors || [];

  const filteredErrors = baseErrors.filter((e: any) =>
    !filterCategory || e.error_category === filterCategory
  );

  // Build error category chart data directly from backend
  const errorCategoryData = stats?.error_categories
    ? Object.entries(stats.error_categories).map(([key, count]) => ({
        name: stats.error_category_labels?.[key] || key,
        key,
        value: count as number,
        fill: CATEGORY_COLORS[key] || "#9ca3af",
      }))
    : [];

  // Strategy distribution chart directly from backend
  const strategyData = stats?.strategy_distribution
    ? Object.entries(stats.strategy_distribution).map(([k, v]) => ({
        strategy: k.replace(/_/g, " "),
        count: v as number
      }))
    : [];

  return (
    <div className="space-y-8">

      {/* ── Backend Offline Warning ── */}
      {(statsError || errorsError) && (
        <div className="p-4 rounded-2xl border border-rose-200 bg-rose-50 text-rose-800 text-xs flex items-center gap-3 shadow-sm">
          <ShieldAlert className="w-5 h-5 text-rose-600 flex-shrink-0" />
          <div>
            <p className="font-bold uppercase tracking-wider">Telemetry Core Disconnected</p>
            <p className="text-rose-600/90 mt-0.5 font-semibold">Failed to fetch system analytics. Check backend service status.</p>
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Admin &amp; Pipeline Control Center
          </h1>
          <p className="text-slate-500 text-sm sm:text-base font-medium mt-1">
            System diagnostics, active pipeline error telemetry, and security alerts across the cascade stages.
          </p>
        </div>
        <button
          onClick={() => { mutateStats(); mutateErrors(); }}
          className="p-3 text-slate-500 hover:text-indigo-600 bg-white hover:bg-indigo-50/10 rounded-xl transition border border-slate-200 flex items-center justify-center gap-2 self-start sm:self-auto cursor-pointer shadow-sm"
          title="Refresh Data"
          disabled={isRefreshing}
        >
          <RefreshCcw className={`w-4 h-4 ${isRefreshing ? "animate-spin text-indigo-500" : ""}`} />
          <span className="text-xs font-bold uppercase tracking-wider">Sync Log</span>
        </button>
      </header>

      {/* ── System Integrity Diagnostic Check ── */}
      <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 hover:shadow-md transition-all duration-300 space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-4">
          <div className="flex items-center gap-3">
            <div className={`p-2.5 rounded-xl border ${
              systemCheck?.overall_health === "healthy"
                ? "bg-emerald-50 border-emerald-100 text-emerald-700"
                : systemCheck?.overall_health === "unhealthy"
                ? "bg-rose-50 border-rose-100 text-rose-700"
                : "bg-indigo-50 border-indigo-100 text-indigo-700"
            }`}>
              {systemCheck?.overall_health === "healthy" ? (
                <ShieldCheck className="w-5 h-5" />
              ) : (
                <ShieldAlert className="w-5 h-5" />
              )}
            </div>
            <div>
              <h2 className="text-base font-extrabold text-slate-900">System Integrity Diagnostics</h2>
              <p className="text-xs text-slate-500 font-semibold mt-0.5">
                Verify the live heartbeat, responsiveness, and database latency of Vergabepilot&apos;s core pipeline services.
              </p>
            </div>
          </div>
          <button
            onClick={handleSystemCheck}
            disabled={isChecking}
            className="px-5 py-3 rounded-xl text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 cursor-pointer shadow-sm active:scale-95 transition-all flex items-center justify-center gap-2 whitespace-nowrap self-start sm:self-auto"
          >
            {isChecking ? (
              <>
                <RefreshCcw className="w-4 h-4 animate-spin" />
                Running Diagnostics...
              </>
            ) : (
              "Run System Integrity Check"
            )}
          </button>
        </div>

        {checkError && (
          <div className="p-4 bg-rose-50 border border-rose-200 text-rose-800 text-xs rounded-2xl font-bold flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-600" />
            {checkError}
          </div>
        )}

        {/* Diagnostic Results Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
          {[
            {
              key: "database",
              label: "PostgreSQL Database",
              desc: "Primary schema persistence storage",
              icon: <Database className="w-4 h-4" />
            },
            {
              key: "redis",
              label: "Redis Task Broker",
              desc: "Celery task queue & event listener",
              icon: <Activity className="w-4 h-4" />
            },
            {
              key: "storage",
              label: "MinIO S3 Storage",
              desc: "Scraped ZIP/PDF package hosting",
              icon: <Clock className="w-4 h-4" />
            },
            {
              key: "openrouter",
              label: "OpenRouter LLM API",
              desc: "AI code generator & live rates",
              icon: <Globe className="w-4 h-4" />
            },
            {
              key: "workers",
              label: "Celery Task Workers",
              desc: "Background scraper executors",
              icon: <Layers className="w-4 h-4" />
            }
          ].map((srv) => {
            const status = systemCheck?.[srv.key];
            return (
              <div
                key={srv.key}
                className={`p-4 rounded-2xl border transition-all duration-200 flex flex-col justify-between h-36 ${
                  status?.status === "online"
                    ? "bg-emerald-50/10 border-emerald-100 hover:bg-emerald-50/20"
                    : status?.status === "warning"
                    ? "bg-amber-50/15 border-amber-200 hover:bg-amber-50/25"
                    : status?.status === "offline"
                    ? "bg-rose-50/10 border-rose-200 hover:bg-rose-50/20"
                    : "bg-slate-50/20 border-slate-100"
                }`}
              >
                <div className="space-y-1">
                  <div className="flex items-center justify-between">
                    <span className={`p-1.5 rounded-lg ${
                      status?.status === "online"
                        ? "bg-emerald-100 text-emerald-700"
                        : status?.status === "warning"
                        ? "bg-amber-100 text-amber-700"
                        : status?.status === "offline"
                        ? "bg-rose-100 text-rose-700"
                        : "bg-slate-100 text-slate-500"
                    }`}>
                      {srv.icon}
                    </span>
                    <span className={`text-[10px] font-black uppercase tracking-wider px-2 py-0.5 rounded-full ${
                      status?.status === "online"
                        ? "bg-emerald-100 text-emerald-800"
                        : status?.status === "warning"
                        ? "bg-amber-100 text-amber-800"
                        : status?.status === "offline"
                        ? "bg-rose-100 text-rose-800"
                        : "bg-slate-100 text-slate-500"
                    }`}>
                      {status?.status || "Pending"}
                    </span>
                  </div>
                  <h3 className="text-xs font-black text-slate-800 pt-2">{srv.label}</h3>
                  <p className="text-[10px] text-slate-400 font-semibold leading-tight line-clamp-2">{srv.desc}</p>
                </div>
                <div className="pt-2 border-t border-slate-100/50 flex items-center justify-between text-[10px] font-mono">
                  <span className="text-slate-400">
                    {status?.latency_ms ? `Latency: ${status.latency_ms}ms` : "—"}
                  </span>
                  {status && (
                    <button
                      className="text-indigo-600 hover:underline font-bold cursor-pointer"
                      onClick={() => setActiveModalService({ label: srv.label, status: status.status, latency: status.latency_ms, message: status.message })}
                    >
                      Details
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Top Stats Grid ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
        {/* Total Jobs */}
        <div className={`bg-white border border-slate-200 rounded-2xl p-6 shadow-sm hover:shadow-md transition-all duration-300 relative overflow-hidden group ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="absolute right-0 top-0 w-24 h-24 bg-gradient-to-b from-indigo-50/20 to-transparent rounded-bl-full pointer-events-none" />
          <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-wider mb-3">
            <div className="p-1.5 bg-slate-50 rounded-lg border border-slate-100 text-slate-500">
              <Database className="w-3.5 h-3.5" />
            </div>
            Total Jobs
          </div>
          <div className="text-3xl font-extrabold text-slate-800 tracking-tight">{stats?.jobs ?? "—"}</div>
          <div className="text-[10px] text-slate-400 font-semibold mt-1">Total procurement scraper task runs</div>
        </div>

        {/* Total Items */}
        <div className={`bg-white border border-slate-200 rounded-2xl p-6 shadow-sm hover:shadow-md transition-all duration-300 relative overflow-hidden group ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="absolute right-0 top-0 w-24 h-24 bg-gradient-to-b from-violet-50/20 to-transparent rounded-bl-full pointer-events-none" />
          <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-wider mb-3">
            <div className="p-1.5 bg-slate-50 rounded-lg border border-slate-100 text-slate-500">
              <Layers className="w-3.5 h-3.5" />
            </div>
            Total Items
          </div>
          <div className="text-3xl font-extrabold text-slate-800 tracking-tight">{stats?.items ?? "—"}</div>
          <div className="text-[10px] text-slate-400 font-semibold mt-1">Extracted tender items & notices</div>
        </div>

        {/* Success Rate */}
        <div className={`bg-emerald-50/5 border border-emerald-200/60 rounded-2xl p-6 shadow-sm hover:shadow-md transition-all duration-300 relative overflow-hidden group ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="absolute right-0 top-0 w-24 h-24 bg-gradient-to-b from-emerald-100/20 to-transparent rounded-bl-full pointer-events-none" />
          <div className="flex items-center gap-2 text-emerald-600 text-xs font-bold uppercase tracking-wider mb-3">
            <div className="p-1.5 bg-emerald-100/50 rounded-lg text-emerald-700">
              <ShieldCheck className="w-3.5 h-3.5" />
            </div>
            Success Rate
          </div>
          <div className="text-3xl font-extrabold text-emerald-700 tracking-tight">
            {stats ? `${Math.round((stats.item_success_rate ?? 0) * 100)}%` : "—"}
          </div>
          <div className="text-[10px] text-emerald-600/75 font-semibold mt-1">Cascade pipeline success index</div>
        </div>

        {/* Failed Items */}
        <div className={`bg-rose-50/5 border border-rose-200/60 rounded-2xl p-6 shadow-sm hover:shadow-md transition-all duration-300 relative overflow-hidden group ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="absolute right-0 top-0 w-24 h-24 bg-gradient-to-b from-rose-100/20 to-transparent rounded-bl-full pointer-events-none" />
          <div className="flex items-center gap-2 text-rose-600 text-xs font-bold uppercase tracking-wider mb-3">
            <div className="p-1.5 bg-rose-100/50 rounded-lg text-rose-700">
              <AlertTriangle className="w-3.5 h-3.5" />
            </div>
            Failed Items
          </div>
          <div className="text-3xl font-extrabold text-rose-700 tracking-tight">
            {stats?.failed_items ?? errors?.length ?? "—"}
          </div>
          <div className="text-[10px] text-rose-600/75 font-semibold mt-1">Aborted or blocked scraper items</div>
        </div>
      </div>

      {/* ── Needs Manual Action ── */}
      {(needsManual?.items?.length ?? 0) > 0 && (
        <div className="bg-white border border-amber-200 rounded-2xl p-6 shadow-sm">
          <div className="flex items-center gap-2 mb-1">
            <div className="p-1.5 bg-amber-100/60 rounded-lg text-amber-700">
              <ShieldAlert className="w-3.5 h-3.5" />
            </div>
            <h3 className="text-sm font-bold text-slate-800">Needs manual action</h3>
            <span className="ml-1 text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800">
              {needsManual.total}
            </span>
          </div>
          <p className="text-[11px] text-slate-500 font-medium mb-4">
            These URLs can only be resolved by a human (login / CAPTCHA) — not silent failures.
          </p>
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {needsManual.items.map((it: any) => (
              <div key={it.item_id} className="flex items-start justify-between gap-3 p-3 rounded-xl border border-slate-100 bg-slate-50/50">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                      {it.bucket_label}
                    </span>
                    <span className="text-xs font-semibold text-slate-700 truncate">{it.domain}</span>
                  </div>
                  <a href={it.url} target="_blank" rel="noreferrer"
                     className="text-[11px] text-indigo-600 hover:underline truncate block max-w-xl">{it.url}</a>
                  <p className="text-[11px] text-slate-500 mt-0.5">{it.suggested_action}</p>
                </div>
                <a href={`/jobs/${it.job_id}`}
                   className="flex-shrink-0 text-[11px] font-semibold text-slate-500 hover:text-indigo-600 underline">
                  View job
                </a>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Charts Row ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Strategy Distribution */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 flex flex-col shadow-sm">
          <div className="border-b border-slate-100 pb-3 mb-5">
            <h2 className="text-md font-extrabold flex items-center gap-2 text-slate-800">
              <Activity className="w-4 h-4 text-indigo-500" />
              Strategy Distribution Breakdown
            </h2>
            <p className="text-xs text-slate-400 font-semibold mt-0.5">Execution volume across the various cascade fallback strategies.</p>
          </div>
          <div className="flex-1 min-h-[250px]">
            {strategyData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={strategyData}
                  margin={{ top: 10, right: 10, left: -25, bottom: 20 }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis
                    dataKey="strategy"
                    tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 700 }}
                    tickLine={false}
                  />
                  <YAxis tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 700 }} tickLine={false} axisLine={false} />
                  <Tooltip 
                    cursor={{ fill: "#f8fafc" }}
                    contentStyle={{ background: '#0f172a', borderRadius: '12px', border: 'none', color: '#f8fafc', fontWeight: 'bold', fontSize: '11px' }}
                  />
                  <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={45} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-slate-400 text-sm font-semibold py-12">
                No active execution records available.
              </div>
            )}
          </div>
        </div>

        {/* Error Categories Breakdown */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 flex flex-col shadow-sm">
          <div className="border-b border-slate-100 pb-3 mb-5">
            <h2 className="text-md font-extrabold flex items-center gap-2 text-slate-800">
              <AlertTriangle className="w-4 h-4 text-rose-500" />
              Error Category Diagnostics
            </h2>
            <p className="text-xs text-slate-400 font-semibold mt-0.5">Categorized pipeline errors to highlight site blocking or connection timeouts.</p>
          </div>
          <div className="flex-1 min-h-[250px] flex items-center justify-center">
            {errorCategoryData.length > 0 ? (
              <div className="flex flex-col sm:flex-row items-center gap-6 w-full">
                <div className="w-[180px] h-[180px] flex-shrink-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={errorCategoryData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        outerRadius={75}
                        innerRadius={45}
                        paddingAngle={3}
                        strokeWidth={0}
                      >
                        {errorCategoryData.map((entry: any, idx: number) => (
                          <Cell key={`cell-${idx}`} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Tooltip
                        contentStyle={{ background: '#0f172a', borderRadius: '12px', border: 'none', color: '#f8fafc', fontWeight: 'bold', fontSize: '11px' }}
                        formatter={(value: number, name: string) => [`${value} errors`, name]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-2 overflow-y-auto max-h-[220px] pr-2 w-full custom-scrollbar">
                  {errorCategoryData
                    .sort((a: any, b: any) => b.value - a.value)
                    .map((cat: any) => (
                      <button
                        key={cat.key}
                        onClick={() => setFilterCategory(filterCategory === cat.key ? null : cat.key)}
                        className={`w-full flex items-center justify-between p-2.5 rounded-xl text-xs transition-all border active:scale-98 cursor-pointer ${
                          filterCategory === cat.key
                            ? "bg-slate-100 border-slate-300 shadow-sm"
                            : "bg-white border-slate-100 hover:border-slate-200 hover:bg-slate-50/50"
                        }`}
                      >
                        <div className="flex items-center gap-2 min-w-0">
                          <span
                            className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                            style={{ backgroundColor: cat.fill }}
                          />
                          <span className="font-bold text-slate-700 truncate">{cat.name}</span>
                        </div>
                        <span className="font-extrabold text-slate-800 ml-2">{cat.value}</span>
                      </button>
                    ))}
                </div>
              </div>
            ) : (
              <div className="text-slate-400 text-sm flex flex-col items-center gap-2 font-semibold py-12">
                <ShieldCheck className="w-10 h-10 text-emerald-500" />
                No errors registered — system running cleanly!
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Error Log ── */}
      <div className="bg-white border border-slate-200/80 rounded-2xl shadow-sm overflow-x-auto max-w-full">
        <div className="px-6 py-4 border-b border-slate-100 bg-gradient-to-r from-rose-50/30 to-white flex flex-wrap justify-between items-center gap-4">
          <h2 className="font-extrabold flex items-center gap-2 text-slate-800">
            <AlertTriangle className="w-5 h-5 text-rose-500" />
            Cascading Pipeline Diagnostics
            <span className="text-xs font-bold bg-rose-100 text-rose-700 px-3 py-1 rounded-full border border-rose-200 ml-2">
              {filteredErrors.length} {filterCategory ? "filtered" : "total"}
            </span>
          </h2>
          <div className="flex items-center gap-2">
            {filterCategory && (
              <button
                onClick={() => setFilterCategory(null)}
                className="flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 bg-slate-100 hover:bg-slate-200 border border-slate-200 rounded-xl text-slate-700 transition-colors cursor-pointer active:scale-95 shadow-sm"
              >
                <XCircle className="w-3.5 h-3.5 text-slate-400" />
                Reset filter
              </button>
            )}
            {filterCategory && (
              <span className="flex items-center gap-1.5 text-xs font-bold text-indigo-700 bg-indigo-50 px-3 py-1.5 rounded-xl border border-indigo-100">
                <Filter className="w-3.5 h-3.5" />
                Category: {stats?.error_category_labels?.[filterCategory] || filterCategory}
              </span>
            )}
          </div>
        </div>

        {filteredErrors.length === 0 ? (
          <div className="py-16 text-center">
            <ShieldCheck className="w-12 h-12 text-emerald-500 mx-auto mb-3" />
            <p className="text-slate-500 font-bold text-sm">
              {filterCategory ? "No errors found matching category criteria." : "All runs successful! Zero pipeline errors."}
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100 max-h-[700px] overflow-y-auto custom-scrollbar">
            {filteredErrors.map((e: any) => {
              const style = SEVERITY_STYLES[e.severity] || SEVERITY_STYLES.info;
              const isExpanded = expandedId === e.id;
              return (
                <li key={e.id} className="hover:bg-slate-50/20 transition-colors">
                  {/* Summary Row */}
                  <button
                    className="w-full p-5 flex items-start gap-4 text-left cursor-pointer"
                    onClick={() => setExpandedId(isExpanded ? null : e.id)}
                  >
                    {/* Severity Indicator */}
                    <div className={`w-3 h-3 rounded-full mt-1.5 flex-shrink-0 ${style.dot}`} />

                    {/* Main Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2.5 mb-2">
                        {/* Error category badge */}
                        <span className={`inline-flex items-center gap-1 px-3 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${style.bg} ${style.text} ${style.border}`}>
                          {e.severity === "critical" && <ShieldAlert className="w-3 h-3" />}
                          {e.error_label}
                        </span>
                        {/* Strategy badge */}
                        <span className="px-2.5 py-0.5 bg-indigo-50 border border-indigo-100 text-indigo-700 rounded-full text-[10px] font-bold">
                          {e.strategy_label}
                        </span>
                        {/* Iterations */}
                        <span className="flex items-center gap-1 text-[10px] font-bold text-slate-400">
                          <Clock className="w-3.5 h-3.5" />
                          {e.iterations} iters · {e.runtime_seconds}s
                        </span>
                      </div>

                      {/* URL */}
                      <div className="flex items-center gap-2 text-xs font-bold text-slate-600 font-mono truncate bg-slate-50 border border-slate-100 p-2.5 rounded-xl w-full" title={e.url}>
                        <Globe className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                        <span className="truncate">{e.url}</span>
                      </div>
                    </div>

                    {/* Expand chevron */}
                    <div className="text-slate-300 mt-1 flex-shrink-0 p-1.5 bg-slate-100 rounded-lg">
                      {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
                    </div>
                  </button>

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <div className="px-5 pb-5 ml-7 space-y-4 ">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-100">
                          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Target Host Domain</div>
                          <div className="text-xs font-bold text-slate-800 font-mono break-all">{e.domain}</div>
                        </div>
                        <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-100">
                          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Resolved Strategy</div>
                          <div className="text-xs font-bold text-slate-800">{e.strategy_label}</div>
                        </div>
                        <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-100">
                          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Failure Classification</div>
                          <div className="text-xs font-bold text-slate-800">{e.error_label}</div>
                        </div>
                      </div>
                      <div className={`p-4 rounded-xl border text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-[300px] overflow-y-auto ${style.bg} ${style.border} ${style.text} leading-relaxed select-all shadow-inner`}>
                        {e.error_message || "No telemetry details logged."}
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {/* ── System Maintenance & Recovery Grid ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Platform Maintenance & Data Purging */}
        <div className="bg-rose-50/10 border border-rose-200/85 rounded-2xl p-6 md:p-8 hover:shadow transition-all duration-300 flex flex-col justify-between space-y-5">
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-rose-100 border border-rose-200 text-rose-700 rounded-xl">
                <Trash2 className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-extrabold text-slate-900">Platform Data Purging</h2>
                <p className="text-xs text-slate-500 font-semibold mt-0.5">Erases all scraping notices, PDF packages, leaderboard telemetry, and logs.</p>
              </div>
            </div>

            {resetSuccess && (
              <div className="p-4 bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs rounded-2xl font-bold">
                ✓ Platform data completely erased!
              </div>
            )}
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 bg-white p-5 rounded-xl border border-rose-100">
            <div className="flex-1 space-y-1.5">
              <p className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider">Confirm DB Reset</p>
              <input 
                type="text" 
                value={resetConfirm}
                onChange={(e) => setResetConfirm(e.target.value)}
                placeholder="Type RESET"
                className="w-full px-3.5 py-2.5 border border-slate-200 rounded-xl text-xs font-mono uppercase focus:ring-2 focus:ring-rose-500 focus:outline-none bg-slate-50/50"
              />
            </div>

            <button
              onClick={handleReset}
              disabled={resetConfirm.toLowerCase() !== "reset" || isResetting}
              className={`px-5 py-3 rounded-xl text-xs font-bold text-white transition-all flex items-center justify-center gap-2 whitespace-nowrap self-end ${
                resetConfirm === "RESET" && !isResetting
                  ? "bg-rose-600 hover:bg-rose-700 cursor-pointer shadow-sm active:scale-95"
                  : "bg-slate-300 cursor-not-allowed"
              }`}
            >
              {isResetting ? (
                <>
                  <RefreshCcw className="w-4 h-4 animate-spin" />
                  Purging...
                </>
              ) : (
                "Purge DB Data"
              )}
            </button>
          </div>
        </div>

        {/* Stuck Jobs Recovery */}
        <div className="bg-indigo-50/10 border border-indigo-200 rounded-2xl p-6 md:p-8 hover:shadow transition-all duration-300 flex flex-col justify-between space-y-5">
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-indigo-50 border border-indigo-100 text-indigo-700 rounded-xl">
                <Clock className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-extrabold text-slate-900">Stuck Jobs Recovery</h2>
                <p className="text-xs text-slate-500 font-semibold mt-0.5">Detects and fails tasks that got stuck due to unexpected restarts.</p>
              </div>
            </div>

            {resetJobsSuccess && (
              <div className="p-4 bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs rounded-2xl font-bold">
                ✓ Successfully aborted zombie tasks!
              </div>
            )}
          </div>

          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 bg-white p-5 rounded-xl border border-indigo-50">
            <div className="text-[11px] text-slate-500 font-medium leading-relaxed pr-2">
              Transitions all <span className="bg-amber-100 text-amber-800 font-mono font-bold px-1.5 py-0.5 rounded">running</span> or <span className="bg-blue-100 text-blue-800 font-mono font-bold px-1.5 py-0.5 rounded">pending</span> jobs into failed states.
            </div>

            <button
              onClick={handleResetStaleJobs}
              disabled={isResettingJobs}
              className="px-5 py-3 rounded-xl text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 cursor-pointer shadow-sm active:scale-95 transition-all flex items-center justify-center gap-2 whitespace-nowrap"
            >
              {isResettingJobs ? (
                <>
                  <RefreshCcw className="w-4 h-4 animate-spin" />
                  Recovering...
                </>
              ) : (
                "Reset Stuck Jobs"
              )}
            </button>
          </div>
        </div>
      </div>

      {/* ── Immersive Details Modal ── */}
      {activeModalService && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-md animate-fade-in">
          <div className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 max-w-lg w-full mx-4 shadow-2xl relative space-y-5 ">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <span className={`w-2.5 h-2.5 rounded-full animate-ping ${
                  activeModalService.status === "online" ? "bg-emerald-500" : activeModalService.status === "warning" ? "bg-amber-500" : "bg-rose-500"
                }`} />
                <h3 className="text-md font-extrabold text-slate-800">{activeModalService.label} Diagnostics</h3>
              </div>
              <button
                onClick={() => setActiveModalService(null)}
                className="p-1.5 hover:bg-slate-100 rounded-lg text-slate-400 hover:text-slate-600 transition cursor-pointer"
              >
                <XCircle className="w-5 h-5" />
              </button>
            </div>
            
            <div className="space-y-4">
              <div className="flex items-center justify-between text-xs font-bold text-slate-500 bg-slate-50 p-3 rounded-xl border border-slate-100">
                <span>Heartbeat Status:</span>
                <span className={`px-2.5 py-0.5 rounded-full uppercase tracking-wider text-[10px] font-black ${
                  activeModalService.status === "online" ? "bg-emerald-100 text-emerald-800" : activeModalService.status === "warning" ? "bg-amber-100 text-amber-800" : "bg-rose-100 text-rose-800"
                }`}>
                  {activeModalService.status}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs font-bold text-slate-500 bg-slate-50 p-3 rounded-xl border border-slate-100">
                <span>Response Latency:</span>
                <span className="font-mono text-slate-800 font-black">{activeModalService.latency ? `${activeModalService.latency} ms` : "—"}</span>
              </div>

              <div className="space-y-1.5">
                <span className="text-[10px] font-extrabold text-slate-400 uppercase tracking-wider block">Raw Telemetry Log Payload</span>
                <div className="bg-slate-900 text-slate-100 p-4 rounded-2xl text-xs font-mono whitespace-pre-wrap leading-relaxed shadow-inner max-h-48 overflow-y-auto custom-scrollbar select-all">
                  {activeModalService.message}
                </div>
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-4 border-t border-slate-100">
              <button
                onClick={() => {
                  navigator.clipboard.writeText(activeModalService.message);
                  toast.success("Copied to clipboard");
                }}
                className="px-4 py-2 border border-slate-200 rounded-xl text-xs font-bold text-slate-600 hover:bg-slate-50 transition active:scale-95 cursor-pointer"
              >
                Copy Payload
              </button>
              <button
                onClick={() => setActiveModalService(null)}
                className="px-5 py-2 bg-slate-900 hover:bg-slate-800 rounded-xl text-xs font-bold text-white transition active:scale-95 cursor-pointer"
              >
                Dismiss Diagnostics
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

