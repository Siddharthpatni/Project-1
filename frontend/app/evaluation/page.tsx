"use client";

import useSWR from "swr";
import { useState } from "react";
import { api, fetcher, postJSON } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell } from "recharts";
import Link from "next/link";
import { Loader2, Play, CheckCircle2, XCircle, ArrowLeft, Award, Layers, DollarSign, Activity, FileText, CheckCircle } from "lucide-react";

const DEFAULT_DATASET = "/app/data/samples/publications_updated.csv";

const AVAILABLE_MODELS = [
  { value: "google/gemini-2.5-flash-lite", label: "Gemini 2.5 Flash Lite" },
  { value: "google/gemini-2.5-flash",      label: "Gemini 2.5 Flash" },
  { value: "google/gemini-2.5-pro",        label: "Gemini 2.5 Pro" },
  { value: "anthropic/claude-sonnet-4.5",  label: "Claude 3.5 Sonnet" },
  { value: "anthropic/claude-haiku-4.5",   label: "Claude 3.5 Haiku" },
  { value: "openai/gpt-4o",               label: "GPT-4o" },
  { value: "openai/gpt-4o-mini",          label: "GPT-4o Mini" },
];

const COLORS = ["#6366f1", "#0ea5e9", "#10b981", "#8b5cf6", "#f59e0b", "#ec4899", "#3b82f6"];

export default function EvaluationPage() {
  const { data: summary, mutate: mutateSummary } = useSWR(api("/evaluation/summary"), fetcher, { refreshInterval: 10_000 });
  const { data: runs,    mutate: mutateRuns }    = useSWR(api("/evaluation/runs?limit=50"), fetcher, { refreshInterval: 5_000 });

  const finalSummary = summary || [];
  const finalRuns = runs || [];

  // Run-trigger state
  const [datasetPath,    setDatasetPath]    = useState(DEFAULT_DATASET);
  const [selectedModels, setSelectedModels] = useState<string[]>(["google/gemini-2.5-flash-lite"]);
  const [maxIters,       setMaxIters]       = useState(3);
  const [running,        setRunning]        = useState(false);
  const [runResult,      setRunResult]      = useState<{ task_id: string } | null>(null);
  const [runError,       setRunError]       = useState<string | null>(null);

  function toggleModel(m: string) {
    setSelectedModels(prev =>
      prev.includes(m) ? prev.filter(x => x !== m) : [...prev, m]
    );
  }

  async function startRun() {
    if (!selectedModels.length) return;
    setRunning(true);
    setRunResult(null);
    setRunError(null);
    try {
      const result = await postJSON<{ task_id: string; status: string }>("/evaluation/run", {
        dataset_path: datasetPath,
        models: selectedModels,
        max_iterations: maxIters,
      });
      setRunResult(result);
      // poll results after a short delay
      setTimeout(() => { mutateSummary(); mutateRuns(); }, 3000);
    } catch (e: any) {
      setRunError(e?.message || "Failed to start evaluation");
    } finally {
      setRunning(false);
    }
  }

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

      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight flex items-center gap-3">
            <Award className="w-8 h-8 text-indigo-600 animate-pulse" />
            Phase 1 — LLM Benchmark Suite
          </h1>
          <p className="text-slate-500 mt-1.5 text-sm sm:text-base font-medium">
            Compare model intelligence on structured notice page extraction and feedback validation.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* ── Run Trigger Card ── */}
        <div className="bg-white border-2 border-dashed border-indigo-200 rounded-3xl p-6 md:p-8 bg-gradient-to-br from-indigo-50/15 via-white to-white space-y-6">
          <div className="flex items-center gap-4">
            <div className="p-3 bg-indigo-50 border border-indigo-150 rounded-2xl">
              <Play className="w-6 h-6 text-indigo-600" />
            </div>
            <div>
              <h2 className="text-lg font-extrabold text-slate-900">Run LLM Benchmark</h2>
              <p className="text-xs text-slate-500 font-medium mt-0.5">
                Evaluate feedback validation loops across URLs using specified LLM architectures.
              </p>
            </div>
          </div>

          {/* Dataset path */}
          <div className="space-y-1.5">
            <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Evaluation Dataset CSV</label>
            <input
              type="text"
              value={datasetPath}
              onChange={e => setDatasetPath(e.target.value)}
              className="w-full px-4 py-3 border border-slate-250 rounded-xl text-sm font-mono focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all shadow-inner bg-white font-medium"
              disabled={running}
            />
            <p className="text-[11px] text-slate-400 font-medium">
              Mounted container path: <code>/app/data/samples/publications_updated.csv</code>.
            </p>
          </div>

          {/* Model selection */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-slate-400 uppercase tracking-wider">Select LLMs to benchmark</label>
              <span className="text-xs font-bold text-indigo-600 bg-indigo-50 px-2.5 py-1 rounded-full border border-indigo-100">
                {selectedModels.length} selected
              </span>
            </div>
            <div className="flex flex-wrap gap-2">
              {AVAILABLE_MODELS.map(m => (
                <button
                  key={m.value}
                  onClick={() => toggleModel(m.value)}
                  disabled={running}
                  className={`px-3.5 py-2 rounded-xl text-xs font-bold border transition-all active:scale-95 cursor-pointer ${
                    selectedModels.includes(m.value)
                      ? "bg-indigo-600 text-white border-indigo-600 shadow-sm"
                      : "bg-white text-slate-650 border-slate-200 hover:border-slate-350 hover:bg-slate-50"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          {/* Max iterations + run button */}
          <div className="flex items-end justify-between pt-4 border-t border-slate-100">
            <div className="space-y-1.5">
              <label className="text-xs font-bold text-slate-400 uppercase tracking-wider block">Max feedback iters</label>
              <input
                type="number"
                min={1}
                max={10}
                value={maxIters}
                onChange={e => setMaxIters(Number(e.target.value))}
                className="w-24 px-3 py-2.5 border border-slate-250 rounded-xl text-sm font-semibold outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm bg-white"
                disabled={running}
              />
            </div>
            <button
              onClick={startRun}
              disabled={running || !selectedModels.length || !datasetPath.trim()}
              className="px-6 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-bold rounded-xl transition-all shadow-sm flex items-center gap-2 cursor-pointer active:scale-95 hover:shadow"
            >
              {running ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Running...
                </>
              ) : (
                <>
                  <Play className="w-4 h-4" />
                  Run Benchmark
                </>
              )}
            </button>
          </div>

          {/* Feedback */}
          {runResult && (
            <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-2xl flex items-center gap-2.5 text-xs font-bold text-emerald-700 animate-in fade-in duration-300">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              Task Queued Successfully — ID: <code className="font-mono text-[11px] font-extrabold bg-white px-2 py-0.5 border rounded text-indigo-700">{runResult.task_id}</code>.
            </div>
          )}
          {runError && (
            <div className="p-4 bg-rose-50 border border-rose-200 rounded-2xl flex items-center gap-2.5 text-xs font-bold text-rose-700 animate-shake">
              <XCircle className="w-4 h-4 flex-shrink-0" />
              {runError}
            </div>
          )}
        </div>

        {/* ── Summary Chart ── */}
        <div className="bg-white border border-slate-200 rounded-3xl p-6 md:p-8 flex flex-col min-h-[380px] shadow-sm">
          <div className="border-b border-slate-100 pb-3 mb-4">
            <h2 className="text-md font-bold text-slate-800">Success Rate Benchmark (Phase 1)</h2>
            <p className="text-xs text-slate-400 font-semibold mt-0.5">Real-time extraction accuracy per evaluated LLM provider.</p>
          </div>
          {(!finalSummary || finalSummary.length === 0) ? (
            <div className="flex-1 flex flex-col items-center justify-center text-slate-400 text-sm py-12">
              <Activity className="w-8 h-8 text-slate-300 mb-2" />
              No benchmark statistics recorded. Initiate a run above.
            </div>
          ) : (
            <div className="flex-1 min-h-[250px] mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={finalSummary} margin={{ top: 10, right: 10, left: -25, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis dataKey="model" stroke="#94a3b8" fontSize={9} angle={-15} textAnchor="end" fontStyle="italic" />
                  <YAxis stroke="#94a3b8" fontSize={10} domain={[0, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} />
                  <Tooltip 
                    cursor={{ fill: "#f8fafc" }} 
                    contentStyle={{ background: '#0f172a', borderRadius: '12px', border: 'none', color: '#f8fafc', fontWeight: 'bold', fontSize: '11px' }}
                    formatter={(v: number) => [`${Math.round(v * 100)}%`, 'Accuracy']} 
                  />
                  <Bar dataKey="success_rate" radius={[4, 4, 0, 0]} maxBarSize={45}>
                    {finalSummary.map((entry: any, index: number) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* ── Summary Leaderboard Table ── */}
        <div className="bg-white border border-slate-200/80 rounded-2xl shadow-sm overflow-hidden lg:col-span-2">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2 bg-slate-50/50">
            <Layers className="w-5 h-5 text-slate-550" />
            <h2 className="font-extrabold text-slate-800">Aggregate Leaderboard</h2>
          </div>
          <div className="overflow-x-auto overflow-y-auto max-h-[600px] custom-scrollbar">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-500 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
                <tr>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider">Model Architecture</th>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Runs</th>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Accuracy</th>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Avg Iters</th>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Avg Time</th>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-right">Total Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(!finalSummary || finalSummary.length === 0) && (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-400 font-semibold">
                      Leaderboard is empty. Compile evaluations above.
                    </td>
                  </tr>
                )}
                {finalSummary?.map((s: any) => (
                  <tr key={s.model} className="hover:bg-slate-50/30 transition-colors">
                    <td className="px-6 py-4 font-mono text-xs">
                      <span className="bg-indigo-50 border border-indigo-100 px-2.5 py-1 rounded-lg text-indigo-700 font-bold">
                        {s.model}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-center font-bold text-slate-700">{s.runs}</td>
                    <td className="px-6 py-4 text-center">
                      <span className={`inline-flex items-center gap-1 text-xs font-bold px-2.5 py-1 rounded-full border ${
                        s.success_rate >= 0.7 ? "bg-emerald-50 text-emerald-700 border-emerald-100" :
                        s.success_rate >= 0.4 ? "bg-amber-50 text-amber-700 border-amber-100" :
                        "bg-rose-50 text-rose-700 border-rose-100"
                      }`}>
                        {Math.round(s.success_rate * 100)}%
                      </span>
                    </td>
                    <td className="px-6 py-4 text-center text-slate-500 font-bold">{s.avg_iterations?.toFixed(1) || 0}</td>
                    <td className="px-6 py-4 text-center text-slate-500 font-bold">{s.avg_runtime_s?.toFixed(1) || 0}s</td>
                    <td className="px-6 py-4 text-right font-bold text-slate-800">${s.total_cost_usd?.toFixed(4) || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Recent Runs Logs Panel ── */}
        <div className="bg-white border border-slate-200/80 rounded-2xl shadow-sm p-6 flex flex-col h-[500px]">
          <div className="border-b border-slate-100 pb-3 mb-4 flex items-center justify-between">
            <h2 className="font-extrabold text-slate-800">Recent Logs</h2>
            <span className="text-[10px] font-bold text-indigo-650 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-100 uppercase tracking-wide">Live SWR Feed</span>
          </div>
          <div className="flex-1 overflow-y-auto pr-1 custom-scrollbar space-y-3">
            {(!finalRuns || finalRuns.length === 0) ? (
              <div className="h-full flex items-center justify-center text-xs text-slate-400 font-semibold py-8">
                No recent run data logs available.
              </div>
            ) : (
              finalRuns.map((r: any) => (
                <div 
                  key={r.id} 
                  className="p-4 rounded-xl border border-slate-200/85 hover:border-slate-350 hover:bg-slate-50/50 transition-colors flex flex-col gap-2.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className={`flex items-center gap-1 text-[11px] font-extrabold uppercase tracking-wide ${
                      r.success ? "text-emerald-700" : "text-rose-700"
                    }`}>
                      {r.success ? <CheckCircle className="w-4 h-4 text-emerald-650" /> : <XCircle className="w-4 h-4 text-rose-650" />}
                      {r.success ? "Accurate" : "Mismatched"}
                    </span>
                    <span className="bg-slate-100 border border-slate-200 px-2 py-0.5 rounded text-[10px] font-bold text-slate-600 truncate max-w-[150px]">
                      {r.model.split('/').pop()}
                    </span>
                  </div>
                  <div className="text-[11px] font-mono font-bold text-slate-500 truncate w-full" title={r.url}>
                    {r.url}
                  </div>
                  <div className="flex flex-wrap gap-2 text-[10px] font-bold text-slate-400 mt-1 border-t border-slate-100/60 pt-2.5">
                    <span className="text-slate-650 bg-slate-150 px-1.5 py-0.5 rounded">Docs: {r.downloaded_docs ?? 0}/{r.expected_docs ?? 0}</span>
                    <span className="text-slate-650 bg-slate-150 px-1.5 py-0.5 rounded">Iters: {r.iterations}</span>
                    <span className="text-emerald-700 bg-emerald-50 border border-emerald-100 px-1.5 py-0.5 rounded">${r.cost_usd?.toFixed(4)}</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}