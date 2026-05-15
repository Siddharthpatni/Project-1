"use client";

import useSWR from "swr";
import { useState } from "react";
import { api, fetcher, postJSON } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";
import { Loader2, Play, CheckCircle2, XCircle } from "lucide-react";

const DEFAULT_DATASET = "/app/data/samples/eval_dataset.jsonl";

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
      <header>
        <h1 className="text-2xl font-bold">Phase 1 — LLM Benchmark</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Compare multiple LLMs on the annotated evaluation dataset. Success rate, iterations, cost.
        </p>
      </header>

      {/* ── Run Trigger Card ── */}
      <div className="card p-6 border-2 border-dashed border-brand-200 bg-gradient-to-br from-brand-50 to-white space-y-4">
        <div className="flex items-center gap-2">
          <div className="p-2 bg-brand-100 rounded-lg">
            <Play className="w-5 h-5 text-brand-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Run Evaluation</h2>
            <p className="text-xs text-slate-500">
              Runs the feedback loop on each URL in the dataset and records results per model.
            </p>
          </div>
        </div>

        {/* Dataset path */}
        <div className="space-y-1">
          <label className="text-sm font-medium text-slate-700">Dataset path (inside container)</label>
          <input
            type="text"
            value={datasetPath}
            onChange={e => setDatasetPath(e.target.value)}
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none"
            disabled={running}
          />
          <p className="text-xs text-slate-400">
            Default dataset mounted at <code>/app/data/samples/eval_dataset.jsonl</code>.
            Drop any <code>.jsonl</code> in <code>./data/</code> on the host — it appears at <code>/app/data/</code>.
          </p>
        </div>

        {/* Model selection */}
        <div className="space-y-2">
          <label className="text-sm font-medium text-slate-700">Models to benchmark</label>
          <div className="flex flex-wrap gap-2">
            {AVAILABLE_MODELS.map(m => (
              <button
                key={m.value}
                onClick={() => toggleModel(m.value)}
                disabled={running}
                className={`px-3 py-1 rounded-full text-xs font-medium border transition-all ${
                  selectedModels.includes(m.value)
                    ? "bg-brand-600 text-white border-brand-600"
                    : "bg-white text-slate-600 border-slate-300 hover:border-brand-400"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-slate-400">{selectedModels.length} model(s) selected</p>
        </div>

        {/* Max iterations + run button */}
        <div className="flex items-end gap-4">
          <div className="space-y-1">
            <label className="text-sm font-medium text-slate-700">Max iterations per URL</label>
            <input
              type="number"
              min={1}
              max={10}
              value={maxIters}
              onChange={e => setMaxIters(Number(e.target.value))}
              className="w-24 px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-brand-500"
              disabled={running}
            />
          </div>
          <button
            onClick={startRun}
            disabled={running || !selectedModels.length || !datasetPath.trim()}
            className="btn-primary px-6 flex items-center gap-2 disabled:opacity-50"
          >
            {running ? (
              <><Loader2 className="w-4 h-4 animate-spin" />Queuing…</>
            ) : (
              <><Play className="w-4 h-4" />Run Benchmark</>
            )}
          </button>
        </div>

        {/* Feedback */}
        {runResult && (
          <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg flex items-center gap-2 text-sm text-emerald-700">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            Queued — task <code className="font-mono text-xs">{runResult.task_id}</code>.
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
      <div className="card p-6">
        <h2 className="font-semibold mb-4">Success rate by model</h2>
        {(!summary || summary.length === 0) ? (
          <p className="text-sm text-slate-400 text-center py-10">No data yet — run a benchmark above.</p>
        ) : (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={summary}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                <XAxis dataKey="model" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={12} domain={[0, 1]} tickFormatter={v => `${Math.round(v * 100)}%`} />
                <Tooltip formatter={(v: number) => `${Math.round(v * 100)}%`} />
                <Bar dataKey="success_rate" fill="#0d9488" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      {/* ── Summary Table ── */}
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-3 font-medium">Model</th>
              <th className="px-4 py-3 font-medium">Runs</th>
              <th className="px-4 py-3 font-medium">Success rate</th>
              <th className="px-4 py-3 font-medium">Avg iters</th>
              <th className="px-4 py-3 font-medium">Avg runtime</th>
              <th className="px-4 py-3 font-medium">Total cost</th>
            </tr>
          </thead>
          <tbody>
            {(!summary || summary.length === 0) && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-500">No evaluation runs yet.</td></tr>
            )}
            {summary?.map((s: any) => (
              <tr key={s.model} className="border-t border-slate-100">
                <td className="px-4 py-3 font-mono text-xs">{s.model}</td>
                <td className="px-4 py-3">{s.runs}</td>
                <td className="px-4 py-3">
                  <span className={`font-semibold ${s.success_rate >= 0.7 ? "text-emerald-600" : s.success_rate >= 0.4 ? "text-amber-600" : "text-rose-600"}`}>
                    {Math.round(s.success_rate * 100)}%
                  </span>
                </td>
                <td className="px-4 py-3">{s.avg_iterations}</td>
                <td className="px-4 py-3">{s.avg_runtime_s}s</td>
                <td className="px-4 py-3">${s.total_cost_usd}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Recent runs log ── */}
      <div className="card p-6">
        <h2 className="font-semibold mb-3">Recent runs</h2>
        {(!runs || runs.length === 0) ? (
          <p className="text-sm text-slate-400">No runs yet.</p>
        ) : (
          <ul className="text-xs space-y-1 max-h-64 overflow-auto font-mono">
            {runs.map((r: any) => (
              <li key={r.id} className={r.success ? "text-emerald-700" : "text-rose-700"}>
                {r.success ? "✓" : "✗"} {r.model} — {r.url} — {r.downloaded_docs}/{r.expected_docs} docs — {r.iterations} iters
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}