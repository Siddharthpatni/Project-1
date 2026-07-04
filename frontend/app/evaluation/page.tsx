/**
 * Evaluation page — LLM benchmark results and live pipeline analytics.
 *
 * Two views (tabbed):
 *
 *   LLM Benchmark (Phase 1):
 *     - Per-model comparison: success rate, avg iterations, avg cost, avg runtime
 *     - Historical benchmark run list (trigger new runs from here)
 *     - Source: GET /api/evaluation/summary + GET /api/evaluation/runs
 *
 *   Pipeline Analytics (Phase 3, real job data):
 *     - By-strategy success rates with cost breakdown
 *     - By-platform success rates (DTVP, NetServer, eVergabe, etc.)
 *     - Top failure categories across all processed URLs
 *     - Scraper registry health report (healthy / degraded / retiring)
 *     - Source: GET /api/evaluation/pipeline + GET /api/evaluation/scraper-health
 *
 * The benchmark tab lets you trigger a new Phase 1 LLM benchmark run via
 * POST /api/evaluation/run, which queues a Celery task and returns a task_id.
 */
"use client";

import useSWR from "swr";
import { useState } from "react";
import { api, fetcher, postJSON } from "@/lib/api";
import { usd } from "@/lib/format";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  Cell, PieChart, Pie, Legend,
} from "recharts";
import Link from "next/link";
import {
  Loader2, Play, CheckCircle2, XCircle, Award, Layers,
  DollarSign, Activity, TrendingUp, Database, Zap, AlertTriangle,
  CheckCircle, Clock, ShieldCheck, RefreshCcw,
} from "lucide-react";

// ── Constants ──────────────────────────────────────────────────────────────

const AVAILABLE_MODELS = [
  { value: "google/gemini-2.5-flash",      label: "Gemini 2.5 Flash" },
  { value: "google/gemini-2.5-flash-lite", label: "Gemini 2.5 Flash Lite" },
  { value: "google/gemini-2.5-pro",        label: "Gemini 2.5 Pro" },
  { value: "anthropic/claude-sonnet-4.5",  label: "Claude Sonnet" },
  { value: "anthropic/claude-haiku-4.5",   label: "Claude Haiku" },
  { value: "openai/gpt-4o",                label: "GPT-4o" },
  { value: "openai/gpt-4o-mini",           label: "GPT-4o Mini" },
];

const STRATEGY_COLORS: Record<string, string> = {
  existing_scraper:       "#6366f1",
  deterministic_template: "#10b981",
  adaptive_universal:     "#0ea5e9",
  llm_generated_scraper:  "#8b5cf6",
  learned_route:          "#14b8a6",
  computer_use_agent:     "#ec4899",
  manual_scraper:         "#3b82f6",
  none:                   "#f43f5e",
};

const HEALTH_STYLES: Record<string, string> = {
  healthy:  "bg-emerald-50 text-emerald-700 border-emerald-200",
  degraded: "bg-amber-50  text-amber-700  border-amber-200",
  retiring: "bg-rose-50   text-rose-700   border-rose-200",
  untested: "bg-slate-50  text-slate-500  border-slate-200",
};

const FAILURE_COLORS = [
  "#f43f5e","#f97316","#eab308","#a855f7","#ec4899",
  "#14b8a6","#6366f1","#0ea5e9","#84cc16","#64748b",
];

function pct(v: number) { return `${Math.round(v * 100)}%`; }

// ── Sub-components ──────────────────────────────────────────────────────────

function KpiCard({ icon: Icon, label, value, sub, color = "indigo" }: {
  icon: any; label: string; value: string | number; sub?: string; color?: string;
}) {
  const cmap: Record<string, string> = {
    indigo:  "text-indigo-600 bg-indigo-50",
    emerald: "text-emerald-600 bg-emerald-50",
    rose:    "text-rose-600 bg-rose-50",
    amber:   "text-amber-600 bg-amber-50",
  };
  return (
    <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
      <div className="flex items-center gap-3 mb-3">
        <div className={`p-2 rounded-xl ${cmap[color] ?? cmap.indigo}`}>
          <Icon className="w-4 h-4" />
        </div>
        <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{label}</span>
      </div>
      <p className="text-2xl font-extrabold text-slate-900">{value}</p>
      {sub && <p className="text-[11px] text-slate-400 font-medium mt-1">{sub}</p>}
    </div>
  );
}

// ── Pipeline Analytics Tab ──────────────────────────────────────────────────

function PipelineTab() {
  const { data: pipeline, mutate } = useSWR(api("/evaluation/pipeline"), fetcher, { refreshInterval: 15_000 });
  const { data: health } = useSWR(api("/evaluation/scraper-health"), fetcher, { refreshInterval: 15_000 });

  if (!pipeline) return (
    <div className="flex items-center justify-center py-24 gap-3 text-slate-400">
      <Loader2 className="w-5 h-5 animate-spin text-indigo-500" />
      <span className="text-sm font-medium">Loading pipeline analytics…</span>
    </div>
  );

  const { totals, by_strategy, by_platform, by_failure } = pipeline;
  const by_attempts: any[] = pipeline.by_attempts ?? [];

  return (
    <div className="space-y-8">
      {/* Headline KPIs */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <KpiCard icon={Layers}     label="URLs Processed"  value={totals.total.toLocaleString()} color="indigo" />
        <KpiCard icon={CheckCircle2} label="Success Rate"  value={pct(totals.success_rate)}
                 sub={`${totals.success} of ${totals.total}`} color="emerald" />
        <KpiCard icon={XCircle}    label="Failed"          value={totals.failed} color="rose" />
        <KpiCard icon={DollarSign} label="Total LLM Cost"  value={usd(totals.total_cost_usd)} color="amber" />
      </div>

      {/* Strategy Performance */}
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
          <Zap className="w-5 h-5 text-indigo-500" />
          <h2 className="font-bold text-slate-800">Strategy Performance</h2>
          <span className="ml-auto text-[10px] text-slate-400 font-medium">from real job data</span>
        </div>
        <div className="p-6 grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Bar chart */}
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={by_strategy} layout="vertical" margin={{ left: 10, right: 20 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#f1f5f9" />
                <XAxis type="number" domain={[0, 1]} tickFormatter={v => `${Math.round(v*100)}%`}
                       fontSize={10} stroke="#94a3b8" />
                {/* width 80 wrapped "Existing (Cached)" / "Universal Adaptive" into two cramped lines */}
                <YAxis type="category" dataKey="label" fontSize={10} stroke="#94a3b8" width={120} />
                <Tooltip
                  formatter={(v: number) => [`${Math.round(v*100)}%`, "Success Rate"]}
                  contentStyle={{ background: "#0f172a", borderRadius: "10px", border: "none", color: "#f8fafc", fontSize: "11px" }}
                />
                <Bar dataKey="success_rate" radius={[0, 4, 4, 0]} maxBarSize={28}>
                  {by_strategy.map((s: any) => (
                    <Cell key={s.strategy} fill={STRATEGY_COLORS[s.strategy] ?? "#64748b"} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Table */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-100">
                  {["Strategy","URLs","Success","Avg Time","Cost"].map(h => (
                    <th key={h} className="pb-2 font-bold text-slate-400 uppercase tracking-wide text-left first:pl-0 pl-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {by_strategy.map((s: any) => (
                  <tr key={s.strategy} className="hover:bg-slate-50/50">
                    <td className="py-2 font-semibold">
                      <span className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full flex-shrink-0"
                              style={{ background: STRATEGY_COLORS[s.strategy] ?? "#64748b" }} />
                        {s.label}
                      </span>
                    </td>
                    <td className="py-2 pl-3 font-mono text-slate-600">{s.total}</td>
                    <td className="py-2 pl-3">
                      <span className={`px-1.5 py-0.5 rounded font-bold ${
                        s.success_rate >= 0.7 ? "bg-emerald-50 text-emerald-700" :
                        s.success_rate >= 0.4 ? "bg-amber-50 text-amber-700" : "bg-rose-50 text-rose-600"
                      }`}>{pct(s.success_rate)}</span>
                    </td>
                    <td className="py-2 pl-3 font-mono text-slate-500">{s.avg_runtime_s}s</td>
                    <td className="py-2 pl-3 font-mono text-slate-500">{usd(s.total_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Attempt-level success ratios — every strategy tried, not just winners */}
      {by_attempts.length > 0 && (
        <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
            <Zap className="w-5 h-5 text-emerald-500" />
            <h2 className="font-bold text-slate-800">Attempt-Level Success Ratios</h2>
            <span className="ml-auto text-[10px] text-slate-400 font-medium">
              every cascade attempt — manual, deterministic &amp; LLM included, not only winning strategies
            </span>
          </div>
          <div className="p-6 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-100">
                  {["Strategy", "Attempts", "Successes", "Success Ratio", "Avg Time"].map(h => (
                    <th key={h} className="pb-2 font-bold text-slate-400 uppercase tracking-wide text-left first:pl-0 pl-3">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {by_attempts.map((s: any) => (
                  <tr key={s.strategy} className="hover:bg-slate-50/50">
                    <td className="py-2 font-semibold">
                      <span className="flex items-center gap-1.5">
                        <span className="w-2 h-2 rounded-full flex-shrink-0"
                              style={{ background: STRATEGY_COLORS[s.strategy] ?? "#64748b" }} />
                        {s.label}
                      </span>
                    </td>
                    <td className="py-2 pl-3 font-mono text-slate-600">{s.attempts}</td>
                    <td className="py-2 pl-3 font-mono text-slate-600">{s.successes}</td>
                    <td className="py-2 pl-3">
                      <span className={`px-1.5 py-0.5 rounded font-bold ${
                        s.success_ratio >= 0.7 ? "bg-emerald-50 text-emerald-700" :
                        s.success_ratio >= 0.4 ? "bg-amber-50 text-amber-700" : "bg-rose-50 text-rose-600"
                      }`}>{pct(s.success_ratio)}</span>
                    </td>
                    <td className="py-2 pl-3 font-mono text-slate-500">{s.avg_duration_s}s</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Platform + Failure side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* By platform */}
        <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
          <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-indigo-500" />
            <h2 className="font-bold text-slate-800 text-sm">Success by Platform</h2>
          </div>
          <div className="overflow-y-auto max-h-64 custom-scrollbar">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50 border-b border-slate-100">
                <tr>
                  {["Platform","URLs","Rate","Best Strategy"].map(h => (
                    <th key={h} className="px-4 py-2.5 font-bold text-slate-400 uppercase tracking-wide text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {by_platform.map((p: any) => (
                  <tr key={p.platform} className="hover:bg-slate-50/50">
                    <td className="px-4 py-2.5 font-mono font-semibold text-slate-700">{p.platform}</td>
                    <td className="px-4 py-2.5 text-slate-500">{p.total}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        p.success_rate >= 0.7 ? "bg-emerald-50 text-emerald-700" :
                        p.success_rate >= 0.4 ? "bg-amber-50 text-amber-700" : "bg-rose-50 text-rose-600"
                      }`}>{pct(p.success_rate)}</span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-500 text-[10px]">
                      <span className="px-1.5 py-0.5 rounded border"
                            style={{ borderColor: `${STRATEGY_COLORS[p.dominant_strategy] ?? "#64748b"}40`,
                                     background: `${STRATEGY_COLORS[p.dominant_strategy] ?? "#64748b"}10`,
                                     color: STRATEGY_COLORS[p.dominant_strategy] ?? "#64748b" }}>
                        {p.dominant_label}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Failure categories */}
        <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
          <div className="px-5 py-3.5 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-rose-500" />
            <h2 className="font-bold text-slate-800 text-sm">Top Failure Reasons</h2>
          </div>
          {by_failure.length === 0 ? (
            <div className="flex items-center justify-center py-12 text-slate-400 text-sm">
              No failures recorded — all URLs succeeded.
            </div>
          ) : (
            <div className="p-4 flex flex-wrap gap-2">
              {by_failure.map((f: any, i: number) => (
                <div key={f.category}
                     className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border text-xs font-semibold"
                     style={{ borderColor: `${FAILURE_COLORS[i % FAILURE_COLORS.length]}40`,
                              background:   `${FAILURE_COLORS[i % FAILURE_COLORS.length]}10`,
                              color:        FAILURE_COLORS[i % FAILURE_COLORS.length] }}>
                  <span>{f.category.replace(/_/g, " ")}</span>
                  <span className="bg-white/70 px-1.5 py-0.5 rounded-full font-bold text-[10px]">{f.count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Scraper Registry Health */}
      {health && (
        <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-slate-100 bg-slate-50 flex items-center gap-3">
            <Database className="w-5 h-5 text-indigo-500" />
            <h2 className="font-bold text-slate-800">Scraper Registry Health</h2>
            <div className="ml-auto flex gap-2 text-[10px] font-bold">
              {[
                { label: "Healthy",  val: health.summary.healthy,  cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
                { label: "Degraded", val: health.summary.degraded, cls: "bg-amber-50 text-amber-700 border-amber-200" },
                { label: "Retiring", val: health.summary.retiring, cls: "bg-rose-50 text-rose-700 border-rose-200" },
                { label: "Untested", val: health.summary.untested, cls: "bg-slate-50 text-slate-500 border-slate-200" },
              ].map(s => (
                <span key={s.label} className={`px-2.5 py-1 rounded-full border ${s.cls}`}>
                  {s.label}: {s.val}
                </span>
              ))}
            </div>
          </div>
          <div className="overflow-x-auto overflow-y-auto max-h-72 custom-scrollbar">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50/95 border-b border-slate-100">
                <tr>
                  {["Domain","Source","Health","Runs","Success Rate","Avg Time","CUA Hint"].map(h => (
                    <th key={h} className="px-4 py-3 font-bold text-slate-400 uppercase tracking-wide text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-50">
                {health.scrapers.map((s: any) => (
                  <tr key={s.domain} className="hover:bg-slate-50/50">
                    <td className="px-4 py-2.5 font-mono text-slate-700 font-semibold text-[11px]">{s.domain}</td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                        s.source === "disk"   ? "bg-amber-50 text-amber-700 border-amber-200" :
                        s.source === "llm"    ? "bg-purple-50 text-purple-700 border-purple-200" :
                        s.source === "manual" ? "bg-blue-50 text-blue-700 border-blue-200" :
                        s.source === "cua"    ? "bg-rose-50 text-rose-700 border-rose-200" :
                        "bg-slate-50 text-slate-500 border-slate-200"
                      }`}>{s.source}</span>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${HEALTH_STYLES[s.health] ?? HEALTH_STYLES.untested}`}>
                        {s.health}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 text-slate-500 font-mono">{s.total_runs}</td>
                    <td className="px-4 py-2.5">
                      {s.success_rate !== null
                        ? <span className={`font-bold ${s.success_rate >= 0.7 ? "text-emerald-600" : s.success_rate >= 0.3 ? "text-amber-600" : "text-rose-600"}`}>
                            {pct(s.success_rate)}
                          </span>
                        : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-slate-500">{s.avg_runtime_s}s</td>
                    <td className="px-4 py-2.5">
                      {s.has_cua_hint
                        ? <span className="px-1.5 py-0.5 bg-rose-50 text-rose-700 border border-rose-200 rounded text-[10px] font-bold">✓ CUA</span>
                        : <span className="text-slate-300">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// ── LLM Benchmark Tab ───────────────────────────────────────────────────────

const CHART_COLORS = ["#6366f1","#0ea5e9","#10b981","#8b5cf6","#f59e0b","#ec4899","#3b82f6"];

function LLMBenchmarkTab() {
  const { data: summary, mutate: mutateSummary } = useSWR(api("/evaluation/summary"), fetcher, { refreshInterval: 10_000 });
  const { data: runs,    mutate: mutateRuns }    = useSWR(api("/evaluation/runs?limit=50"), fetcher, { refreshInterval: 5_000 });

  const [datasetPath,    setDatasetPath]    = useState("/app/data/samples/publications_updated.csv");
  const [selectedModels, setSelectedModels] = useState<string[]>(["google/gemini-2.5-flash"]);
  const [maxIters,       setMaxIters]       = useState(3);
  const [running,        setRunning]        = useState(false);
  const [runResult,      setRunResult]      = useState<{ task_id: string } | null>(null);
  const [runError,       setRunError]       = useState<string | null>(null);

  function toggleModel(m: string) {
    setSelectedModels(p => p.includes(m) ? p.filter(x => x !== m) : [...p, m]);
  }

  async function startRun() {
    if (!selectedModels.length) return;
    setRunning(true); setRunResult(null); setRunError(null);
    try {
      const r = await postJSON<{ task_id: string; status: string }>("/evaluation/run", {
        dataset_path: datasetPath, models: selectedModels, max_iterations: maxIters,
      });
      setRunResult(r);
      setTimeout(() => { mutateSummary(); mutateRuns(); }, 3000);
    } catch (e: any) {
      setRunError(e?.message || "Failed to start evaluation");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Run trigger */}
        <div className="bg-white border-2 border-dashed border-indigo-200 rounded-2xl p-6 space-y-6">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-indigo-50 border border-indigo-100 rounded-2xl">
              <Play className="w-6 h-6 text-indigo-600" />
            </div>
            <div>
              <h2 className="text-lg font-extrabold text-slate-900">Run LLM Benchmark</h2>
              <p className="text-xs text-slate-500 mt-0.5">Compare model accuracy on scraper generation tasks.</p>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Dataset CSV path</label>
            <input type="text" value={datasetPath} onChange={e => setDatasetPath(e.target.value)}
                   disabled={running}
                   className="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm font-mono focus:ring-2 focus:ring-indigo-500 outline-none" />
          </div>

          <div className="space-y-2">
            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Select models</label>
            <div className="flex flex-wrap gap-2">
              {AVAILABLE_MODELS.map(m => (
                <button key={m.value} onClick={() => toggleModel(m.value)} disabled={running}
                        className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-all cursor-pointer ${
                          selectedModels.includes(m.value)
                            ? "bg-indigo-600 text-white border-indigo-600 shadow-sm"
                            : "bg-white text-slate-600 border-slate-200 hover:border-slate-300"
                        }`}>{m.label}</button>
              ))}
            </div>
          </div>

          <div className="flex items-end justify-between pt-3 border-t border-slate-100">
            <div>
              <label className="text-xs font-bold text-slate-400 uppercase tracking-wider block mb-1">Max iters</label>
              <input type="number" min={1} max={10} value={maxIters}
                     onChange={e => setMaxIters(Number(e.target.value))} disabled={running}
                     className="w-20 px-3 py-2 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:ring-2 focus:ring-indigo-500" />
            </div>
            <button onClick={startRun} disabled={running || !selectedModels.length || !datasetPath.trim()}
                    className="px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-bold rounded-xl transition-all shadow-sm flex items-center gap-2 cursor-pointer">
              {running ? <><Loader2 className="w-4 h-4 animate-spin"/>Running…</> : <><Play className="w-4 h-4"/>Run</>}
            </button>
          </div>

          {runResult && (
            <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl flex items-center gap-2 text-xs font-bold text-emerald-700">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              Queued — task <code className="font-mono bg-white px-1.5 rounded text-indigo-700">{runResult.task_id}</code>
            </div>
          )}
          {runError && (
            <div className="p-3 bg-rose-50 border border-rose-200 rounded-xl flex items-center gap-2 text-xs font-bold text-rose-700">
              <XCircle className="w-4 h-4 flex-shrink-0" />{runError}
            </div>
          )}
        </div>

        {/* Success rate chart */}
        <div className="bg-white border border-slate-200 rounded-2xl p-6 flex flex-col min-h-[320px] shadow-sm">
          <h2 className="font-bold text-slate-800 mb-1">Accuracy by Model</h2>
          <p className="text-xs text-slate-400 mb-4">LLM scraper generation success rate.</p>
          {(!summary || summary.length === 0) ? (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-400 text-sm">
              <Activity className="w-8 h-8 text-slate-300 mb-2" />No benchmark data yet.
            </div>
          ) : (
            <div className="flex-1 min-h-[200px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={summary} margin={{ top: 5, right: 10, left: -25, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis dataKey="model" fontSize={8} angle={-15} textAnchor="end" stroke="#94a3b8" />
                  <YAxis fontSize={10} domain={[0,1]} tickFormatter={v => `${Math.round(v*100)}%`} stroke="#94a3b8" />
                  <Tooltip formatter={(v: number) => [`${Math.round(v*100)}%`, "Accuracy"]}
                           contentStyle={{ background:"#0f172a", borderRadius:"10px", border:"none", color:"#f8fafc", fontSize:"11px" }} />
                  <Bar dataKey="success_rate" radius={[4,4,0,0]} maxBarSize={40}>
                    {summary.map((_: any, i: number) => <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      {/* Leaderboard + Recent logs */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden lg:col-span-2">
          <div className="px-6 py-4 border-b border-slate-100 bg-slate-50 flex items-center gap-2">
            <Layers className="w-5 h-5 text-slate-500" />
            <h2 className="font-bold text-slate-800">Leaderboard</h2>
          </div>
          <div className="overflow-x-auto overflow-y-auto max-h-64 custom-scrollbar">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-50/95 border-b border-slate-100">
                <tr>
                  {["Model","Runs","Accuracy","Avg Iters","Avg Time","Total Cost"].map(h => (
                    <th key={h} className="px-5 py-3 font-bold text-slate-400 uppercase tracking-wide text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(!summary || summary.length === 0) && (
                  <tr><td colSpan={6} className="px-5 py-10 text-center text-slate-400">No runs yet.</td></tr>
                )}
                {summary?.map((s: any) => (
                  <tr key={s.model} className="hover:bg-slate-50/30">
                    <td className="px-5 py-3 font-mono text-[11px]">
                      <span className="bg-indigo-50 border border-indigo-100 px-2 py-0.5 rounded-lg text-indigo-700 font-bold">
                        {s.model.split("/").pop()}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-slate-600 font-bold">{s.runs}</td>
                    <td className="px-5 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-bold border ${
                        s.success_rate >= 0.7 ? "bg-emerald-50 text-emerald-700 border-emerald-100" :
                        s.success_rate >= 0.4 ? "bg-amber-50 text-amber-700 border-amber-100" :
                        "bg-rose-50 text-rose-700 border-rose-100"
                      }`}>{pct(s.success_rate)}</span>
                    </td>
                    <td className="px-5 py-3 text-slate-500 font-bold">{s.avg_iterations?.toFixed(1)}</td>
                    <td className="px-5 py-3 text-slate-500 font-bold">{s.avg_runtime_s?.toFixed(1)}s</td>
                    <td className="px-5 py-3 text-slate-700 font-bold">{usd(s.total_cost_usd ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="bg-white border border-slate-200 rounded-2xl shadow-sm p-5 flex flex-col max-h-64">
          <h2 className="font-bold text-slate-800 mb-3 text-sm">Recent Runs</h2>
          <div className="flex-1 overflow-y-auto space-y-2.5 custom-scrollbar">
            {(!runs || runs.length === 0) ? (
              <p className="text-xs text-slate-400 py-6 text-center">No run history.</p>
            ) : runs.map((r: any) => (
              <div key={r.id} className="p-3 rounded-xl border border-slate-100 hover:bg-slate-50/50 text-xs space-y-1.5">
                <div className="flex items-center gap-2">
                  {r.success
                    ? <CheckCircle className="w-3.5 h-3.5 text-emerald-500 flex-shrink-0" />
                    : <XCircle    className="w-3.5 h-3.5 text-rose-500 flex-shrink-0" />}
                  <span className="font-bold text-slate-700 truncate">{r.model?.split("/").pop()}</span>
                  <span className="ml-auto text-emerald-600 font-bold">{usd(r.cost_usd ?? 0)}</span>
                </div>
                <p className="font-mono text-[10px] text-slate-400 truncate">{r.url}</p>
                <div className="flex gap-2 text-[10px] text-slate-400">
                  <span className="bg-slate-100 px-1.5 py-0.5 rounded">Docs {r.downloaded_docs}/{r.expected_docs}</span>
                  <span className="bg-slate-100 px-1.5 py-0.5 rounded">Iters {r.iterations}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Main Page ───────────────────────────────────────────────────────────────

export default function EvaluationPage() {
  const [tab, setTab] = useState<"pipeline" | "llm">("pipeline");

  return (
    <div className="space-y-8">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Evaluation & Benchmarking
          </h1>
          <p className="text-slate-500 mt-1.5 text-sm font-medium">
            Real pipeline performance analytics + LLM model benchmark suite.
          </p>
        </div>

        {/* Tab switcher */}
        <div className="flex items-center gap-1 bg-slate-100 p-1 rounded-xl">
          <button onClick={() => setTab("pipeline")}
                  className={`px-4 py-2 rounded-lg text-sm font-bold transition-all ${
                    tab === "pipeline" ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-700"
                  }`}>
            Pipeline Analytics
          </button>
          <button onClick={() => setTab("llm")}
                  className={`px-4 py-2 rounded-lg text-sm font-bold transition-all ${
                    tab === "llm" ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-700"
                  }`}>
            LLM Benchmark
          </button>
        </div>
      </header>

      {tab === "pipeline" ? <PipelineTab /> : <LLMBenchmarkTab />}
    </div>
  );
}
