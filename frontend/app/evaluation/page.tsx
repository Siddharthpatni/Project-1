"use client";

import useSWR from "swr";
import { useState } from "react";
import { api, fetcher, postJSON } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import Link from "next/link";
import { Loader2, Play, CheckCircle2, XCircle, ArrowLeft } from "lucide-react";

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
    <div className="space-y-6">
      {/* ── Navigation / Back Button ── */}
      <Link href="/" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-indigo-600 transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Dashboard
      </Link>

      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Play className="w-6 h-6 text-brand-600" />
            Phase 1 — LLM Benchmark
          </h1>
          <p className="text-slate-600 text-sm mt-1">
            Compare multiple LLMs on the annotated evaluation dataset. Success rate, iterations, cost.
          </p>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ── Run Trigger Card ── */}
        <div className="card p-6 border-2 border-dashed border-brand-200 bg-gradient-to-br from-brand-50/50 to-white space-y-5">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-brand-100 rounded-lg">
              <Play className="w-5 h-5 text-brand-600" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-brand-950">Run Evaluation</h2>
              <p className="text-xs text-slate-500">
                Runs the feedback loop on each URL in the dataset and records results per model.
              </p>
            </div>
          </div>

          {/* Dataset path */}
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-slate-700">Dataset path (inside container)</label>
            <input
              type="text"
              value={datasetPath}
              onChange={e => setDatasetPath(e.target.value)}
              className="w-full px-3 py-2.5 border border-slate-300 rounded-lg text-sm font-mono focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition-all shadow-sm"
              disabled={running}
            />
            <p className="text-xs text-slate-400">
              Default dataset mounted at <code>/app/data/samples/publications_updated.csv</code>.
            </p>
          </div>

          {/* Model selection */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-sm font-medium text-slate-700">Models to benchmark</label>
              <span className="text-xs font-semibold text-brand-600 bg-brand-50 px-2 py-0.5 rounded-full">{selectedModels.length} selected</span>
            </div>
            <div className="flex flex-wrap gap-2">
              {AVAILABLE_MODELS.map(m => (
                <button
                  key={m.value}
                  onClick={() => toggleModel(m.value)}
                  disabled={running}
                  className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
                    selectedModels.includes(m.value)
                      ? "bg-brand-600 text-white border-brand-600 shadow-sm"
                      : "bg-white text-slate-600 border-slate-300 hover:border-brand-400 hover:bg-brand-50"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>

          {/* Max iterations + run button */}
          <div className="flex items-end justify-between pt-2 border-t border-slate-100">
            <div className="space-y-1.5">
              <label className="text-sm font-medium text-slate-700 block">Max iterations per URL</label>
              <input
                type="number"
                min={1}
                max={10}
                value={maxIters}
                onChange={e => setMaxIters(Number(e.target.value))}
                className="w-24 px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-brand-500 shadow-sm"
                disabled={running}
              />
            </div>
            <button
              onClick={startRun}
              disabled={running || !selectedModels.length || !datasetPath.trim()}
              className="px-6 py-2.5 bg-brand-600 hover:bg-brand-700 disabled:bg-brand-400 text-white font-medium rounded-lg transition-colors shadow-sm flex items-center gap-2"
            >
              {running ? (
                <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>Queuing…</>
              ) : (
                <><Play className="w-4 h-4" />Run Benchmark</>
              )}
            </button>
          </div>

          {/* Feedback */}
          {runResult && (
            <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg flex items-center gap-2 text-sm text-emerald-700">
              <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
              Queued — task <code className="font-mono text-xs font-bold">{runResult.task_id}</code>.
              Results will appear below as the worker completes each URL.
            </div>
          )}
          {runError && (
            <div className="p-3 bg-rose-50 border border-rose-200 rounded-lg flex items-center gap-2 text-sm text-rose-700">
              <XCircle className="w-4 h-4 flex-shrink-0" />
              {runError}
            </div>
          )}
        </div>

        {/* ── Summary Chart ── */}
        <div className="card p-6 flex flex-col min-h-[350px]">
          <h2 className="font-semibold mb-4">Success rate by model</h2>
          {(!finalSummary || finalSummary.length === 0) ? (
            <p className="text-sm text-slate-400 text-center py-10">No data yet — run a benchmark above.</p>
          ) : (
            <div className="flex-1 min-h-[250px] mt-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={finalSummary} margin={{ top: 10, right: 10, left: 0, bottom: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="model" stroke="#64748b" fontSize={10} angle={-15} textAnchor="end" />
                  <YAxis stroke="#64748b" fontSize={11} domain={[0, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} />
                  <Tooltip cursor={{ fill: "#f8fafc" }} formatter={(v: number) => `${Math.round(v * 100)}%`} />
                  <Bar dataKey="success_rate" fill="#0ea5e9" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ── Summary Table ── */}
        <div className="card overflow-hidden lg:col-span-2">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
            <h2 className="font-semibold text-slate-800">Aggregate Leaderboard</h2>
          </div>
          <div className="overflow-x-auto overflow-y-auto max-h-[600px]">
          <table className="w-full text-sm">
            <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-600 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
              <tr>
                <th className="px-5 py-3 font-medium">Model</th>
                <th className="px-5 py-3 font-medium text-center">Runs</th>
                <th className="px-5 py-3 font-medium text-center">Success Rate</th>
                <th className="px-5 py-3 font-medium text-center">Avg Iters</th>
                <th className="px-5 py-3 font-medium text-center">Avg Runtime</th>
                <th className="px-5 py-3 font-medium text-right">Total Cost</th>
              </tr>
            </thead>
            <tbody>
              {(!finalSummary || finalSummary.length === 0) && (
                <tr><td colSpan={6} className="px-5 py-12 text-center text-slate-500">No evaluation runs yet.</td></tr>
              )}
              {finalSummary?.map((s: any) => (
                <tr key={s.model} className="border-b border-slate-50 hover:bg-slate-50/50 transition-colors">
                  <td className="px-5 py-4 font-mono text-xs">
                    <span className="bg-slate-100 px-2 py-1 rounded text-slate-700 font-semibold">{s.model}</span>
                  </td>
                  <td className="px-5 py-4 text-center">{s.runs}</td>
                  <td className="px-5 py-4 text-center">
                    <span className={`font-semibold ${s.success_rate >= 0.7 ? "text-emerald-600" : s.success_rate >= 0.4 ? "text-amber-600" : "text-rose-600"}`}>
                      {Math.round(s.success_rate * 100)}%
                    </span>
                  </td>
                  <td className="px-5 py-4 text-center text-slate-600">{s.avg_iterations}</td>
                  <td className="px-5 py-4 text-center text-slate-600">{s.avg_runtime_s}s</td>
                  <td className="px-5 py-4 text-right font-medium text-slate-700">${s.total_cost_usd?.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>

        {/* ── Recent runs log ── */}
        <div className="card p-6 flex flex-col h-[500px]">
          <h2 className="font-semibold mb-3">Recent Runs</h2>
          <div className="flex-1 overflow-y-auto pr-2">
            {(!finalRuns || finalRuns.length === 0) ? (
              <div className="h-full flex items-center justify-center text-sm text-slate-400">No runs yet.</div>
            ) : (
              <ul className="text-xs space-y-1.5 font-mono">
                {finalRuns.map((r: any) => (
                  <li key={r.id} className="p-3 rounded-lg border border-slate-100 hover:border-slate-200 hover:bg-slate-50 transition-colors flex flex-col gap-1.5">
                    <div className="flex items-center justify-between">
                      <span className={`flex items-center gap-1.5 font-semibold ${r.success ? "text-emerald-700" : "text-rose-700"}`}>
                        {r.success ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                        {r.success ? "Success" : "Failed"}
                      </span>
                      <span className="bg-slate-100 px-2 py-0.5 rounded text-slate-600 truncate max-w-[120px]">{r.model}</span>
                    </div>
                    <div className="text-slate-600 truncate" title={r.url}>{r.url}</div>
                    <div className="flex gap-3 text-[10px] text-slate-500 mt-1">
                      <span>{r.downloaded_docs ?? 0}/{r.expected_docs ?? 0} docs</span>
                      <span>{r.iterations} iters</span>
                      <span>${r.cost_usd?.toFixed(4)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}