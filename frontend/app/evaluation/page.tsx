"use client";

import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts";

export default function EvaluationPage() {
  const { data: summary } = useSWR(api("/evaluation/summary"), fetcher, { refreshInterval: 10_000 });
  const { data: runs } = useSWR(api("/evaluation/runs?limit=50"), fetcher, { refreshInterval: 10_000 });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Phase 1 — LLM Benchmark</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Compare multiple LLMs on the annotated evaluation dataset. Success rate, iterations, cost.
        </p>
      </header>

      <div className="card p-6">
        <h2 className="font-semibold mb-4">Success rate by model</h2>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={summary || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="model" stroke="#64748b" fontSize={12} />
              <YAxis stroke="#64748b" fontSize={12} domain={[0, 1]} />
              <Tooltip />
              <Bar dataKey="success_rate" fill="#0d9488" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

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
            {summary?.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-500">No evaluation runs yet.</td></tr>
            )}
            {summary?.map((s: any) => (
              <tr key={s.model} className="border-t border-slate-100">
                <td className="px-4 py-3 font-mono text-xs">{s.model}</td>
                <td className="px-4 py-3">{s.runs}</td>
                <td className="px-4 py-3">{Math.round(s.success_rate * 100)}%</td>
                <td className="px-4 py-3">{s.avg_iterations}</td>
                <td className="px-4 py-3">{s.avg_runtime_s}s</td>
                <td className="px-4 py-3">${s.total_cost_usd}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card p-6">
        <h2 className="font-semibold mb-3">Recent runs</h2>
        <ul className="text-xs space-y-1 max-h-64 overflow-auto font-mono">
          {runs?.map((r: any) => (
            <li key={r.id} className={r.success ? "text-emerald-700" : "text-rose-700"}>
              {r.success ? "✓" : "✗"} {r.model} — {r.url} — {r.downloaded_docs}/{r.expected_docs} docs — {r.iterations} iters
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
