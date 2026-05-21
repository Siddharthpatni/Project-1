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
  ArrowLeft,
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

// Severity → visual style
const SEVERITY_STYLES: Record<string, { bg: string; text: string; border: string; dot: string }> = {
  critical: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-250", dot: "bg-rose-500" },
  error:    { bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-250", dot: "bg-orange-500" },
  warning:  { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-250", dot: "bg-amber-500" },
  info:     { bg: "bg-slate-50", text: "text-slate-650", border: "border-slate-200", dot: "bg-slate-400" },
};

// Error category → colors for the pie chart
const CATEGORY_COLORS: Record<string, string> = {
  timeout: "#f59e0b",
  network: "#ef4444",
  dns: "#dc2626",
  ssl: "#b91c1c",
  auth: "#d97706",
  not_found: "#6b7280",
  rate_limit: "#f97316",
  server_error: "#dc2626",
  code_validation: "#7c3aed",
  sandbox: "#be123c",
  prompt_injection: "#e11d48",
  no_documents: "#64748b",
  storage: "#ea580c",
  blocked_url: "#be123c",
  no_strategy: "#94a3b8",
  loop_exhausted: "#ca8a04",
  unknown: "#9ca3af",
};

export default function AdminPage() {
  const { data: stats, error: statsError, isLoading: statsLoading, mutate: mutateStats } = useSWR(api("/admin/stats"), fetcher, { refreshInterval: 10000 });
  const { data: errors, error: errorsError, isLoading: errorsLoading, mutate: mutateErrors } = useSWR(api("/admin/errors"), fetcher, { refreshInterval: 10000 });
  const [filterCategory, setFilterCategory] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const [resetConfirm, setResetConfirm] = useState("");
  const [isResetting, setIsResetting] = useState(false);
  const [resetSuccess, setResetSuccess] = useState(false);

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
        alert("Reset failed");
      }
    } catch (err) {
      alert("Error during reset");
    } finally {
      setIsResetting(false);
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
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
      {/* ── Navigation / Back Button ── */}
      <Link 
        href="/" 
        className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-indigo-650 transition-all hover:translate-x-[-2px] duration-200"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Dashboard
      </Link>

      {/* ── Backend Offline Warning ── */}
      {(statsError || errorsError) && (
        <div className="p-4 rounded-2xl border-2 border-rose-200 bg-rose-50 text-rose-800 text-xs flex items-center gap-3 animate-pulse shadow-sm">
          <ShieldAlert className="w-5 h-5 text-rose-650 flex-shrink-0" />
          <div>
            <p className="font-bold uppercase tracking-wider">Telemetry Core Disconnected</p>
            <p className="text-rose-650/90 mt-0.5 font-semibold">Failed to fetch system analytics. Check backend service status.</p>
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold flex items-center gap-3 text-slate-900 tracking-tight">
            <ShieldAlert className="w-8 h-8 text-rose-500 animate-pulse" />
            Admin &amp; Pipeline Control Center
          </h1>
          <p className="text-slate-500 text-sm sm:text-base font-medium mt-1">
            System diagnostics, active pipeline error telemetry, and security alerts across the cascade stages.
          </p>
        </div>
        <button
          onClick={() => { mutateStats(); mutateErrors(); }}
          className="p-3 text-slate-550 hover:text-indigo-600 bg-white hover:bg-indigo-50/10 rounded-xl transition border border-slate-200 flex items-center justify-center gap-2 self-start sm:self-auto cursor-pointer shadow-sm"
          title="Refresh Data"
          disabled={isRefreshing}
        >
          <RefreshCcw className={`w-4 h-4 ${isRefreshing ? "animate-spin text-indigo-500" : ""}`} />
          <span className="text-xs font-bold uppercase tracking-wider">Sync Log</span>
        </button>
      </header>

      {/* ── Top Stats Grid ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-6">
        <div className={`bg-white border border-slate-200 rounded-2xl p-5 shadow-sm transition-all ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-wider mb-2">
            <Database className="w-4 h-4 text-slate-450" /> Total Jobs
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-slate-800">{stats?.jobs ?? "—"}</div>
        </div>
        <div className={`bg-white border border-slate-200 rounded-2xl p-5 shadow-sm transition-all ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-wider mb-2">
            <Layers className="w-4 h-4 text-slate-450" /> Total Items
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-slate-800">{stats?.items ?? "—"}</div>
        </div>
        <div className={`bg-white border border-emerald-200 rounded-2xl p-5 bg-gradient-to-br from-emerald-50/15 to-white shadow-sm transition-all ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2 text-emerald-600 text-xs font-bold uppercase tracking-wider mb-2">
            <ShieldCheck className="w-4 h-4 text-emerald-500" /> Success Rate
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-emerald-700">
            {stats ? `${Math.round((stats.item_success_rate ?? 0) * 100)}%` : "—"}
          </div>
        </div>
        <div className={`bg-white border border-rose-200 rounded-2xl p-5 bg-gradient-to-br from-rose-50/15 to-white shadow-sm transition-all ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2 text-rose-600 text-xs font-bold uppercase tracking-wider mb-2">
            <AlertTriangle className="w-4 h-4 text-rose-500" /> Failed Items
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-rose-700">
            {stats?.failed_items ?? errors?.length ?? "—"}
          </div>
        </div>
      </div>

      {/* ── Charts Row ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Strategy Distribution */}
        <div className="bg-white border border-slate-200 rounded-3xl p-6 md:p-8 flex flex-col shadow-sm">
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
        <div className="bg-white border border-slate-200 rounded-3xl p-6 md:p-8 flex flex-col shadow-sm">
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
                            ? "bg-slate-100 border-slate-350 shadow-sm"
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
                className="flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 bg-slate-100 hover:bg-slate-200 border border-slate-250 rounded-xl text-slate-700 transition-colors cursor-pointer active:scale-95 shadow-sm"
              >
                <XCircle className="w-3.5 h-3.5 text-slate-450" />
                Reset filter
              </button>
            )}
            {filterCategory && (
              <span className="flex items-center gap-1.5 text-xs font-bold text-indigo-700 bg-indigo-50 px-3 py-1.5 rounded-xl border border-indigo-150">
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
          <ul className="divide-y divide-slate-150 max-h-[700px] overflow-y-auto custom-scrollbar">
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
                    <div className={`w-3 h-3 rounded-full mt-1.5 flex-shrink-0 animate-pulse ${style.dot}`} />

                    {/* Main Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2.5 mb-2">
                        {/* Error category badge */}
                        <span className={`inline-flex items-center gap-1 px-3 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider border ${style.bg} ${style.text} ${style.border}`}>
                          {e.severity === "critical" && <ShieldAlert className="w-3 h-3" />}
                          {e.error_label}
                        </span>
                        {/* Strategy badge */}
                        <span className="px-2.5 py-0.5 bg-indigo-50 border border-indigo-150 text-indigo-700 rounded-full text-[10px] font-bold">
                          {e.strategy_label}
                        </span>
                        {/* Iterations */}
                        <span className="flex items-center gap-1 text-[10px] font-bold text-slate-400">
                          <Clock className="w-3.5 h-3.5" />
                          {e.iterations} iters · {e.runtime_seconds}s
                        </span>
                      </div>

                      {/* URL */}
                      <div className="flex items-center gap-2 text-xs font-bold text-slate-600 font-mono truncate bg-slate-50 border border-slate-150 p-2.5 rounded-xl w-full" title={e.url}>
                        <Globe className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
                        <span className="truncate">{e.url}</span>
                      </div>
                    </div>

                    {/* Expand chevron */}
                    <div className="text-slate-350 mt-1 flex-shrink-0 p-1.5 bg-slate-100 rounded-lg">
                      {isExpanded ? <ChevronDown className="w-4 h-4 text-slate-500" /> : <ChevronRight className="w-4 h-4 text-slate-500" />}
                    </div>
                  </button>

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <div className="px-5 pb-5 ml-7 space-y-4 animate-in slide-in-from-top-1 duration-200">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-150">
                          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Target Host Domain</div>
                          <div className="text-xs font-bold text-slate-800 font-mono break-all">{e.domain}</div>
                        </div>
                        <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-150">
                          <div className="text-[10px] font-bold text-slate-400 uppercase tracking-wider mb-1">Resolved Strategy</div>
                          <div className="text-xs font-bold text-slate-800">{e.strategy_label}</div>
                        </div>
                        <div className="bg-slate-50 p-3.5 rounded-xl border border-slate-150">
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

      {/* ── System Maintenance & Data Purging ── */}
      <div className="bg-rose-50/10 border border-rose-200/80 rounded-2xl p-6 md:p-8 hover:shadow transition-all duration-300 space-y-5">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-rose-100 border border-rose-200 text-rose-700 rounded-xl">
            <Trash2 className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-extrabold text-slate-900">Platform Maintenance &amp; Database Purge</h2>
            <p className="text-xs text-slate-500 font-semibold mt-0.5">Erases all past scraping execution runs, downloaded PDF packages, benchmark leaderboards, and telemetry logs.</p>
          </div>
        </div>

        {resetSuccess && (
          <div className="p-4 bg-emerald-50 border border-emerald-250 text-emerald-800 text-xs rounded-2xl font-bold animate-pulse">
            ✓ Platform data completely erased! All statistics, benchmark runs, and diagnostic logs have been reset to zero.
          </div>
        )}

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 bg-white p-5 rounded-xl border border-rose-100">
          <div className="flex-1 space-y-1.5">
            <p className="text-xs font-bold text-slate-700">Type &quot;RESET&quot; to authorize database purging:</p>
            <input 
              type="text" 
              value={resetConfirm}
              onChange={(e) => setResetConfirm(e.target.value)}
              placeholder="Type RESET"
              className="w-full sm:w-48 px-3.5 py-2.5 border border-slate-250 rounded-xl text-xs font-mono uppercase focus:ring-2 focus:ring-rose-500 focus:outline-none bg-slate-50/50"
            />
          </div>

          <button
            onClick={handleReset}
            disabled={resetConfirm !== "RESET" || isResetting}
            className={`px-5 py-3 rounded-xl text-xs font-bold text-white transition-all flex items-center justify-center gap-2 ${
              resetConfirm === "RESET" && !isResetting
                ? "bg-rose-600 hover:bg-rose-700 cursor-pointer shadow-sm active:scale-95"
                : "bg-slate-350 cursor-not-allowed"
            }`}
          >
            {isResetting ? (
              <>
                <RefreshCcw className="w-4 h-4 animate-spin" />
                Purging Data...
              </>
            ) : (
              "Authorize Database Reset"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
