"use client";

import { useState } from "react";
import useSWR from "swr";
import { api, fetcher, postJSON } from "@/lib/api";
import Link from "next/link";
import { Bot, Play, CheckCircle2, XCircle, Search, Cpu, Activity, Clock, DollarSign, ArrowLeft, X } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from "recharts";

export default function AgentsPage() {
  const { data: summary } = useSWR(api("/agents/summary"), fetcher, { refreshInterval: 6000 });
  const { data: runs, mutate } = useSWR(api("/agents/runs"), fetcher, { refreshInterval: 6000 });

  const finalSummary = summary || [];
  const finalRuns = runs || [];

  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [agentName, setAgentName] = useState("playwright_cua");

  async function trigger() {
    if (!url) return;
    setBusy(true);
    try {
      await postJSON("/agents/run", { agent_name: agentName, url });
      setUrl("");
      setTimeout(() => mutate(), 2000);
    } finally {
      setBusy(false);
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
            <Bot className="w-6 h-6 text-indigo-600" />
            Phase 2 — Computer-Use Agents
          </h1>
          <p className="text-slate-600 text-sm mt-1">
            GUI-based agents that interact with tender websites visually. Used as the ultimate fallback in the cascade.
          </p>
        </div>
      </header>

      {/* ── Trigger Run ── */}
      <div className="card p-6 border-2 border-dashed border-indigo-200 bg-gradient-to-br from-indigo-50/50 to-white">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-indigo-100 rounded-lg">
            <Play className="w-5 h-5 text-indigo-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-indigo-950">Trigger an Agent Run</h2>
            <p className="text-xs text-slate-500">Dispatch a visual GUI agent to manually navigate and download documents.</p>
          </div>
        </div>
        <div className="space-y-3">
          <div className="flex flex-col sm:flex-row gap-3">
            <select
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              className="px-4 py-2.5 border border-slate-300 rounded-lg text-sm bg-white focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all shadow-sm font-medium text-slate-700 sm:w-64"
              disabled={busy}
            >
              <option value="playwright_cua">Playwright CUA (Coordinates & CSS)</option>
              <option value="browser_use">Browser-Use CUA (Language Chain)</option>
            </select>
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                type="url"
                placeholder="https://www.evergabe-online.de/tenderdetails.html..."
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && url.trim() && trigger()}
                className="w-full pl-10 pr-10 py-2.5 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all shadow-sm"
                disabled={busy}
              />
              {url && (
                <button
                  type="button"
                  onClick={() => setUrl("")}
                  className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
            <button 
              onClick={trigger} 
              disabled={busy || !url.trim()} 
              className="flex items-center gap-2 px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-medium rounded-lg transition-all active:scale-[0.98] shadow-sm cursor-pointer"
            >
              {busy ? (
                <span className="flex items-center gap-2"><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>Queuing...</span>
              ) : (
                <span className="flex items-center gap-2"><Cpu className="w-4 h-4" /> Run Agent</span>
              )}
            </button>
          </div>

          {/* Quick-Start Suggestions Row */}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 mr-1">Quick Presets:</span>
            {[
              { label: "DTVP Direct Docs", url: "https://www.dtvp.de/Satellite/public/company/project/CXP4YR1MNRM/de/documents?0" },
              { label: "Evergabe Online", url: "https://www.evergabe-online.de/tenderdetails.html?id=12345" },
              { label: "DTVP Project Summary", url: "https://www.dtvp.de/Satellite/public/company/project/CXP4YR1MNRM/de/about" }
            ].map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => setUrl(preset.url)}
                className="text-xs px-2.5 py-1 bg-white border border-slate-200 hover:border-indigo-400 hover:text-indigo-600 rounded-full font-medium shadow-sm transition-all hover:scale-105 active:scale-95 cursor-pointer"
                disabled={busy}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* ── Summary Stats ── */}
        <div className="lg:col-span-2 card overflow-hidden flex flex-col">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
            <Activity className="w-5 h-5 text-indigo-500" />
            <h2 className="font-semibold text-slate-800">Agent Performance</h2>
          </div>
          <div className="overflow-x-auto overflow-y-auto max-h-[600px] flex-1">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-600 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
                <tr>
                  <th className="px-5 py-3 font-medium">Agent Model</th>
                  <th className="px-5 py-3 font-medium text-center">Runs</th>
                  <th className="px-5 py-3 font-medium text-center">Success Rate</th>
                  <th className="px-5 py-3 font-medium text-center">Avg Steps</th>
                  <th className="px-5 py-3 font-medium text-right">Total Cost</th>
                </tr>
              </thead>
              <tbody>
                {(!finalSummary || finalSummary.length === 0) ? (
                  <tr><td colSpan={5} className="px-5 py-12 text-center text-slate-400">No agent runs recorded yet.</td></tr>
                ) : (
                  finalSummary.map((s: any) => (
                    <tr key={s.agent} className="border-b border-slate-50 hover:bg-slate-50/50 transition-colors">
                      <td className="px-5 py-4">
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-800 font-mono">
                          {s.agent}
                        </span>
                      </td>
                      <td className="px-5 py-4 text-center text-slate-600">{s.runs}</td>
                      <td className="px-5 py-4 text-center">
                        <span className={`font-semibold ${s.success_rate >= 0.7 ? "text-emerald-600" : s.success_rate >= 0.4 ? "text-amber-600" : "text-rose-600"}`}>
                          {Math.round(s.success_rate * 100)}%
                        </span>
                      </td>
                      <td className="px-5 py-4 text-center text-slate-600">{s.avg_steps}</td>
                      <td className="px-5 py-4 text-right font-medium text-slate-700">${s.total_cost_usd?.toFixed(3)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Recent Runs ── */}
        <div className="card flex flex-col h-[400px]">
          <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
            <h2 className="font-semibold text-slate-800 flex items-center gap-2">
              <Clock className="w-5 h-5 text-indigo-500" />
              Recent Executions
            </h2>
          </div>
          <div className="flex-1 overflow-y-auto p-2">
            {(!finalRuns || finalRuns.length === 0) ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-2">
                <Bot className="w-8 h-8 opacity-20" />
                <p className="text-sm">No activity log.</p>
              </div>
            ) : (
              <ul className="space-y-1">
                {finalRuns.map((r: any) => (
                  <li key={r.id} className="p-3 rounded-lg hover:bg-slate-50 transition-colors flex flex-col gap-2 border border-transparent hover:border-slate-100">
                    <div className="flex items-center justify-between">
                      <div className={`flex items-center gap-1.5 text-xs font-semibold ${r.success ? "text-emerald-700" : "text-rose-700"}`}>
                        {r.success ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                        {r.success ? "Success" : "Failed"}
                      </div>
                      <span className="text-[10px] text-slate-400 flex items-center gap-1 font-mono">
                        <DollarSign className="w-3 h-3" />
                        {r.cost_usd?.toFixed(4)}
                      </span>
                    </div>
                    <div className="text-xs text-slate-600 font-mono truncate max-w-[280px]" title={r.url}>
                      {r.url}
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-slate-500">
                      <span className="bg-slate-100 px-1.5 py-0.5 rounded">{r.agent_name}</span>
                      <span>{r.steps} steps</span>
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
