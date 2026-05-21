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
  critical: { bg: "bg-rose-50", text: "text-rose-700", border: "border-rose-200", dot: "bg-rose-500" },
  error:    { bg: "bg-orange-50", text: "text-orange-700", border: "border-orange-200", dot: "bg-orange-500" },
  warning:  { bg: "bg-amber-50", text: "text-amber-700", border: "border-amber-200", dot: "bg-amber-500" },
  info:     { bg: "bg-slate-50", text: "text-slate-600", border: "border-slate-200", dot: "bg-slate-400" },
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
    <div className="space-y-6">
      {/* ── Navigation / Back Button ── */}
      <Link href="/" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-indigo-600 transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Dashboard
      </Link>

      {/* ── Backend Offline Warning ── */}
      {(statsError || errorsError) && (
        <div className="p-4 rounded-xl border border-rose-200 bg-rose-50 text-rose-800 text-xs flex items-center gap-3 animate-pulse">
          <ShieldAlert className="w-5 h-5 text-rose-600 flex-shrink-0" />
          <div>
            <p className="font-bold">Backend Connection Issue</p>
            <p className="text-rose-600/90 mt-0.5">Failed to fetch real-time analytics. Please check if the backend service is running.</p>
          </div>
        </div>
      )}

      {/* ── Header ── */}
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-extrabold flex items-center gap-2 text-slate-900">
            <ShieldAlert className="w-6 h-6 text-rose-500" />
            Admin &amp; Pipeline Monitor
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            System health, error diagnostics, and security alerts across all pipeline phases.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => { mutateStats(); mutateErrors(); }}
            className="p-2.5 text-slate-500 hover:bg-slate-100 rounded-lg transition border border-slate-200 flex items-center gap-2"
            title="Refresh Data"
            disabled={isRefreshing}
          >
            <RefreshCcw className={`w-4 h-4 ${isRefreshing ? "animate-spin text-indigo-500" : ""}`} />
          </button>
        </div>
      </header>

      {/* ── Top Stats Grid ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className={`card p-5 bg-gradient-to-br from-slate-50 to-white transition-all ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2 text-slate-500 text-xs font-medium mb-1">
            <Database className="w-3.5 h-3.5" /> Total Jobs
          </div>
          <div className="text-3xl font-bold text-slate-800">{stats?.jobs ?? "—"}</div>
        </div>
        <div className={`card p-5 bg-gradient-to-br from-slate-50 to-white transition-all ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2 text-slate-500 text-xs font-medium mb-1">
            <Layers className="w-3.5 h-3.5" /> Total Items
          </div>
          <div className="text-3xl font-bold text-slate-800">{stats?.items ?? "—"}</div>
        </div>
        <div className={`card p-5 bg-gradient-to-br from-emerald-50/50 to-white transition-all ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2 text-emerald-600 text-xs font-medium mb-1">
            <ShieldCheck className="w-3.5 h-3.5" /> Success Rate
          </div>
          <div className="text-3xl font-bold text-emerald-700">
            {stats ? `${Math.round((stats.item_success_rate ?? 0) * 100)}%` : "—"}
          </div>
        </div>
        <div className={`card p-5 bg-gradient-to-br from-rose-50/50 to-white transition-all ${isRefreshing && !stats ? "animate-pulse" : ""}`}>
          <div className="flex items-center gap-2 text-rose-600 text-xs font-medium mb-1">
            <AlertTriangle className="w-3.5 h-3.5" /> Failed Items
          </div>
          <div className="text-3xl font-bold text-rose-700">
            {stats?.failed_items ?? errors?.length ?? "—"}
          </div>
        </div>
      </div>

      {/* ── Charts Row ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Strategy Distribution */}
        <div className="card p-6 flex flex-col">
          <h2 className="font-bold mb-4 flex items-center gap-2 text-slate-800">
            <Activity className="w-4 h-4 text-indigo-500" />
            Strategy Distribution
          </h2>
          <div className="flex-1 min-h-[250px]">
            {strategyData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={strategyData}
                  margin={{ top: 10, right: 10, left: 0, bottom: 20 }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis
                    dataKey="strategy"
                    tick={{ fill: "#64748b", fontSize: 10 }}
                    tickLine={false}
                  />
                  <YAxis tick={{ fill: "#64748b", fontSize: 10 }} tickLine={false} axisLine={false} />
                  <Tooltip cursor={{ fill: "#f8fafc" }} />
                  <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-slate-400 text-sm">
                No data available
              </div>
            )}
          </div>
        </div>

        {/* Error Categories Breakdown */}
        <div className="card p-6 flex flex-col">
          <h2 className="font-bold mb-4 flex items-center gap-2 text-slate-800">
            <AlertTriangle className="w-4 h-4 text-rose-500" />
            Error Category Breakdown
          </h2>
          <div className="flex-1 min-h-[250px] flex items-center justify-center">
            {errorCategoryData.length > 0 ? (
              <div className="flex items-center gap-6 w-full">
                <div className="w-[200px] h-[200px] flex-shrink-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={errorCategoryData}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        outerRadius={80}
                        innerRadius={40}
                        paddingAngle={2}
                        strokeWidth={0}
                      >
                        {errorCategoryData.map((entry: any, idx: number) => (
                          <Cell key={`cell-${idx}`} fill={entry.fill} />
                        ))}
                      </Pie>
                      <Tooltip
                        formatter={(value: number, name: string) => [`${value} errors`, name]}
                      />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <div className="flex-1 space-y-1.5 overflow-y-auto max-h-[220px] pr-2">
                  {errorCategoryData
                    .sort((a: any, b: any) => b.value - a.value)
                    .map((cat: any) => (
                      <button
                        key={cat.key}
                        onClick={() => setFilterCategory(filterCategory === cat.key ? null : cat.key)}
                        className={`w-full flex items-center justify-between p-2 rounded-lg text-xs transition-all border ${
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
                          <span className="font-medium text-slate-700 truncate">{cat.name}</span>
                        </div>
                        <span className="font-bold text-slate-800 ml-2">{cat.value}</span>
                      </button>
                    ))}
                </div>
              </div>
            ) : (
              <div className="text-slate-400 text-sm flex flex-col items-center gap-2">
                <ShieldCheck className="w-8 h-8 text-emerald-400" />
                No errors recorded — system is healthy!
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Error Log ── */}
      <div className="card overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-100 bg-gradient-to-r from-rose-50/50 to-white flex justify-between items-center">
          <h2 className="font-bold flex items-center gap-2 text-slate-800">
            <AlertTriangle className="w-4 h-4 text-rose-500" />
            Pipeline Error Log
            <span className="text-xs font-semibold bg-rose-100 text-rose-700 px-2.5 py-0.5 rounded-full ml-2">
              {filteredErrors.length} {filterCategory ? "filtered" : "total"}
            </span>
          </h2>
          <div className="flex items-center gap-2">
            {filterCategory && (
              <button
                onClick={() => setFilterCategory(null)}
                className="flex items-center gap-1 text-xs px-3 py-1.5 bg-slate-100 hover:bg-slate-200 rounded-lg text-slate-700 transition-colors"
              >
                <XCircle className="w-3 h-3" />
                Clear filter
              </button>
            )}
            {filterCategory && (
              <span className="flex items-center gap-1.5 text-xs font-medium text-indigo-700 bg-indigo-50 px-3 py-1.5 rounded-lg border border-indigo-100">
                <Filter className="w-3 h-3" />
                {stats?.error_category_labels?.[filterCategory] || filterCategory}
              </span>
            )}
          </div>
        </div>

        {filteredErrors.length === 0 ? (
          <div className="p-12 text-center">
            <ShieldCheck className="w-10 h-10 text-emerald-400 mx-auto mb-3" />
            <p className="text-slate-500 font-medium">
              {filterCategory ? "No errors match this filter." : "No recent failures. System is healthy!"}
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-slate-100 max-h-[700px] overflow-y-auto">
            {filteredErrors.map((e: any) => {
              const style = SEVERITY_STYLES[e.severity] || SEVERITY_STYLES.info;
              const isExpanded = expandedId === e.id;
              return (
                <li key={e.id} className="hover:bg-slate-50/50 transition-colors">
                  {/* Summary Row */}
                  <button
                    className="w-full p-4 flex items-start gap-3 text-left"
                    onClick={() => setExpandedId(isExpanded ? null : e.id)}
                  >
                    {/* Severity Indicator */}
                    <div className={`w-2.5 h-2.5 rounded-full mt-1.5 flex-shrink-0 ${style.dot}`} />

                    {/* Main Content */}
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-wrap items-center gap-2 mb-1.5">
                        {/* Error category badge */}
                        <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${style.bg} ${style.text} border ${style.border}`}>
                          {e.severity === "critical" && <ShieldAlert className="w-3 h-3" />}
                          {e.error_label}
                        </span>
                        {/* Strategy badge */}
                        <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded-full text-[10px] font-semibold border border-indigo-100">
                          {e.strategy_label}
                        </span>
                        {/* Iterations */}
                        <span className="flex items-center gap-1 text-[10px] text-slate-400">
                          <Clock className="w-3 h-3" />
                          {e.iterations} iter · {e.runtime_seconds}s
                        </span>
                      </div>

                      {/* URL */}
                      <div className="flex items-center gap-1.5 text-xs text-slate-600 font-mono truncate" title={e.url}>
                        <Globe className="w-3 h-3 text-slate-400 flex-shrink-0" />
                        <span className="truncate">{e.url}</span>
                      </div>
                    </div>

                    {/* Expand chevron */}
                    <div className="text-slate-300 mt-1 flex-shrink-0">
                      {isExpanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
                    </div>
                  </button>

                  {/* Expanded Detail */}
                  {isExpanded && (
                    <div className="px-4 pb-4 ml-6">
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
                        <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
                          <div className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1">Domain</div>
                          <div className="text-xs font-semibold text-slate-800 font-mono">{e.domain}</div>
                        </div>
                        <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
                          <div className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1">Strategy Phase</div>
                          <div className="text-xs font-semibold text-slate-800">{e.strategy_label}</div>
                        </div>
                        <div className="bg-slate-50 p-3 rounded-lg border border-slate-100">
                          <div className="text-[10px] font-medium text-slate-500 uppercase tracking-wider mb-1">Error Category</div>
                          <div className="text-xs font-semibold text-slate-800">{e.error_label}</div>
                        </div>
                      </div>
                      <div className={`p-3 rounded-lg border text-xs font-mono whitespace-pre-wrap overflow-x-auto max-h-[300px] overflow-y-auto ${style.bg} ${style.border} ${style.text}`}>
                        {e.error_message || "No error message recorded."}
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
      <div className="card p-6 border border-rose-250 bg-rose-50/10 hover:shadow-md transition-all duration-300 space-y-4">
        <div className="flex items-center gap-2.5">
          <div className="p-2 bg-rose-100 text-rose-700 rounded-lg">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base font-bold text-slate-900">System Maintenance &amp; Database Purge</h2>
            <p className="text-xs text-slate-500 mt-0.5">Permanently erase all scraping runs, saved documents, metrics, and error logs.</p>
          </div>
        </div>

        {resetSuccess && (
          <div className="p-3 bg-emerald-100 border border-emerald-250 text-emerald-800 text-xs rounded-xl font-bold animate-pulse">
            ✓ Database successfully wiped! All statistics and logs have been reset to zero.
          </div>
        )}

        <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-4 bg-white p-4 rounded-xl border border-rose-100">
          <div className="flex-1 space-y-1">
            <p className="text-xs font-bold text-slate-700">Type &quot;RESET&quot; to confirm purging:</p>
            <input 
              type="text" 
              value={resetConfirm}
              onChange={(e) => setResetConfirm(e.target.value)}
              placeholder="Type RESET"
              className="w-full sm:w-48 px-3 py-2 border border-slate-250 rounded-lg text-xs font-mono uppercase focus:ring-1 focus:ring-rose-500 focus:outline-none"
            />
          </div>

          <button
            onClick={handleReset}
            disabled={resetConfirm !== "RESET" || isResetting}
            className={`px-5 py-2.5 rounded-xl text-xs font-bold text-white transition-all flex items-center justify-center gap-2 ${
              resetConfirm === "RESET" && !isResetting
                ? "bg-rose-600 hover:bg-rose-700 cursor-pointer shadow-sm"
                : "bg-slate-350 cursor-not-allowed"
            }`}
          >
            {isResetting ? (
              <>
                <RefreshCcw className="w-4 h-4 animate-spin" />
                Purging Data...
              </>
            ) : (
              "Delete Database Data"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
