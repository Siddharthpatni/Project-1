"use client";

import { useState } from "react";
import useSWR from "swr";
import { api, fetcher, postJSON } from "@/lib/api";

export default function AgentsPage() {
  const { data: summary } = useSWR(api("/agents/summary"), fetcher, { refreshInterval: 6000 });
  const { data: runs } = useSWR(api("/agents/runs"), fetcher, { refreshInterval: 6000 });

  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  async function trigger() {
    if (!url) return;
    setBusy(true);
    try {
      await postJSON("/agents/run", { agent_name: "playwright_cua", url });
      setUrl("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Phase 2 — Computer-Use Agents</h1>
        <p className="text-slate-600 mt-1 text-sm">
          GUI-based agents that interact with tender websites visually. Used as fallback in the cascade.
        </p>
      </header>

      <div className="card p-6">
        <h2 className="font-semibold mb-3">Trigger an agent run</h2>
        <div className="flex gap-3">
          <input
            type="url"
            placeholder="https://www.evergabe-online.de/tenderdetails…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm"
          />
          <button onClick={trigger} disabled={busy || !url} className="btn-primary disabled:opacity-50">
            {busy ? "Queuing…" : "Run agent"}
          </button>
        </div>
      </div>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-3 font-medium">Agent</th>
              <th className="px-4 py-3 font-medium">Runs</th>
              <th className="px-4 py-3 font-medium">Success rate</th>
              <th className="px-4 py-3 font-medium">Avg steps</th>
              <th className="px-4 py-3 font-medium">Avg runtime</th>
              <th className="px-4 py-3 font-medium">Total cost</th>
            </tr>
          </thead>
          <tbody>
            {summary?.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-500">No agent runs yet.</td></tr>
            )}
            {summary?.map((s: any) => (
              <tr key={s.agent} className="border-t border-slate-100">
                <td className="px-4 py-3 font-mono text-xs">{s.agent}</td>
                <td className="px-4 py-3">{s.runs}</td>
                <td className="px-4 py-3">{Math.round(s.success_rate * 100)}%</td>
                <td className="px-4 py-3">{s.avg_steps}</td>
                <td className="px-4 py-3">{s.avg_runtime_s}s</td>
                <td className="px-4 py-3">${s.total_cost_usd}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card p-6">
        <h2 className="font-semibold mb-3">Recent agent runs</h2>
        <ul className="text-xs space-y-1 max-h-64 overflow-auto font-mono">
          {runs?.map((r: any) => (
            <li key={r.id} className={r.success ? "text-emerald-700" : "text-rose-700"}>
              {r.success ? "✓" : "✗"} {r.agent_name} — {r.url} — {r.steps} steps — ${r.cost_usd?.toFixed(4)}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
