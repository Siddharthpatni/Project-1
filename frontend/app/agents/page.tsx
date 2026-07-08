/**
 * CUA Agent Runs page — trigger and inspect Phase 2 computer-use agent sessions.
 *
 * The Computer-Use Agent (CUA) is the last-resort strategy in the cascade:
 * a vision-capable LLM (e.g. GPT-4o) drives a real Chromium browser to navigate
 * procurement portals and click download buttons — used when all other strategies fail.
 *
 * Features:
 *   - Run form: submit a URL + agent type + max steps to trigger a CUA session
 *   - Run history table: past sessions with success/failure, cost, step count
 *   - Session detail: expand to see the full action trace from each run
 *
 * Agent types registered in the backend orchestrator:
 *   playwright_cua — primary, with CRITICAL RULES prompt (used in production cascade)
 *   browser_use    — secondary, simpler prompt (for benchmarking only)
 *
 * Data sources:
 *   GET  /api/agents          → list historical CUA runs
 *   POST /api/agents/run      → trigger a new CUA session (async, returns run_id)
 */
"use client";

import { useState } from "react";
import useSWR from "swr";
import { api, fetcher, postJSON } from "@/lib/api";
import { usd } from "@/lib/format";
import Link from "next/link";
import {
  Bot, CheckCircle2, XCircle, Search, Cpu, Activity, Clock,
  DollarSign, X, Sparkles, Zap, Timer, Hash,
  RefreshCcw, Globe, ExternalLink, FileText
} from "lucide-react";

export default function AgentsPage() {
  const { data: summary } = useSWR(api("/agents/summary"), fetcher, { refreshInterval: 6000 });
  const { data: runs, mutate } = useSWR(api("/agents/runs"), fetcher, { refreshInterval: 6000 });

  const finalSummary = summary || [];
  const finalRuns = runs || [];

  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [agentName, setAgentName] = useState("playwright_cua");
  const [modelName, setModelName] = useState("openai/gpt-4o-mini");

  async function trigger() {
    if (!url) return;
    setBusy(true);
    try {
      await postJSON("/agents/run", { 
        agent_name: agentName, 
        url,
        model_name: modelName 
      });
      setUrl("");
      setTimeout(() => mutate(), 2000);
    } finally {
      setBusy(false);
    }
  }

  // Calculate overview stats from summary
  const totalRuns = finalSummary.reduce((acc: number, s: any) => acc + s.runs, 0);
  const totalCost = finalSummary.reduce((acc: number, s: any) => acc + (s.total_cost_usd || 0), 0);
  const avgSuccessRate = finalSummary.length > 0
    ? finalSummary.reduce((acc: number, s: any) => acc + s.success_rate, 0) / finalSummary.length
    : 0;

  return (
    <div className="space-y-8">

      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Computer-Use Agents
          </h1>
          <p className="text-slate-500 text-sm sm:text-base font-medium mt-1">
            GUI-based autonomous agent that visually navigates procurement portals to discover and download tender files.
          </p>
        </div>
        <button
          onClick={() => mutate()}
          className="self-start sm:self-auto p-2.5 bg-white border border-slate-200 rounded-xl hover:bg-slate-50 transition-all text-slate-500 hover:text-indigo-600 cursor-pointer"
          title="Refresh data"
        >
          <RefreshCcw className="w-4 h-4" />
        </button>
      </header>

      {/* ── Overview KPI Cards ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
          <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-wider mb-2">
            <Hash className="w-4 h-4" /> Total Agent Runs
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-slate-800">{totalRuns}</div>
        </div>
        <div className="bg-white border border-emerald-200 rounded-2xl p-5 bg-gradient-to-br from-emerald-50/15 to-white shadow-sm">
          <div className="flex items-center gap-2 text-emerald-600 text-xs font-bold uppercase tracking-wider mb-2">
            <CheckCircle2 className="w-4 h-4" /> Avg Success Rate
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-emerald-700">
            {Math.round(avgSuccessRate * 100)}%
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm">
          <div className="flex items-center gap-2 text-slate-400 text-xs font-bold uppercase tracking-wider mb-2">
            <DollarSign className="w-4 h-4" /> Total LLM Cost
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-slate-800">{usd(totalCost)}</div>
        </div>
      </div>

      {/* ── Trigger Run Form ── */}
      <div className="bg-white border-2 border-dashed border-indigo-200 rounded-2xl p-6 md:p-8 bg-gradient-to-br from-indigo-50/15 via-white to-white space-y-6">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-indigo-50 border border-indigo-100 rounded-2xl">
            <Sparkles className="w-6 h-6 text-indigo-600" />
          </div>
          <div>
            <h2 className="text-lg font-extrabold text-slate-900">Trigger Autonomous Agent Session</h2>
            <p className="text-xs text-slate-500 font-semibold mt-0.5">Dispatch a browser-use CUA agent to visually navigate and download procurement documents.</p>
          </div>
        </div>
        
        <div className="space-y-4">
          <div className="flex flex-col xl:flex-row gap-4 items-stretch xl:items-end">
            <div className="flex flex-col sm:flex-row gap-4 flex-wrap">


              <div className="flex flex-col gap-1.5">
                <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Vision LLM Model</label>
                <select
                  value={modelName}
                  onChange={(e) => setModelName(e.target.value)}
                  className="px-4 py-3 border border-slate-200 rounded-xl text-xs bg-white focus:ring-2 focus:ring-indigo-500 outline-none transition-all font-bold text-slate-700 w-full sm:w-56 cursor-pointer"
                  disabled={busy}
                >
                  <option value="openai/gpt-4o-mini">GPT-4o Mini (High-Speed & stable)</option>
                  <option value="openai/gpt-4o">GPT-4o</option>
                  <option value="google/gemini-2.5-flash">Gemini 2.5 Flash</option>
                  <option value="google/gemini-2.5-pro">Gemini 2.5 Pro</option>
                  <option value="anthropic/claude-sonnet-4">Claude Sonnet 4</option>
                  <option value="ollama/gemma4:12b">Gemma 4 12B · Local, free</option>
                </select>
              </div>
            </div>

            <div className="flex-1 flex flex-col gap-1.5">
              <label className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Notice Page URL</label>
              <div className="relative w-full">
                <Globe className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
                <input
                  type="url"
                  placeholder="https://www.evergabe-online.de/tenderdetails.html..."
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && url.trim() && trigger()}
                  className="w-full pl-10 pr-10 py-3 border border-slate-200 rounded-xl text-xs focus:ring-2 focus:ring-indigo-500 outline-none transition-all bg-white font-medium"
                  disabled={busy}
                />
                {url && (
                  <button
                    type="button"
                    onClick={() => setUrl("")}
                    className="absolute right-3.5 top-1/2 -translate-y-1/2 p-1 rounded-full text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors cursor-pointer"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                )}
              </div>
            </div>

            <button 
              onClick={trigger} 
              disabled={busy || !url.trim()} 
              className="flex items-center justify-center gap-2 px-6 py-3 bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white font-bold rounded-xl transition-all shadow-sm cursor-pointer active:scale-95 text-xs uppercase tracking-wider whitespace-nowrap"
            >
              {busy ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Queuing...
                </>
              ) : (
                <>
                  <Zap className="w-4 h-4" /> 
                  Run CUA
                </>
              )}
            </button>
          </div>

          {/* Quick-Start Presets */}
          <div className="flex flex-wrap items-center gap-2 pt-3 border-t border-slate-100">
            <span className="text-[10px] font-bold uppercase tracking-wider text-slate-400 mr-2">Quick Presets:</span>
            {[
              { label: "DTVP Docs", url: "https://www.dtvp.de/Satellite/public/company/project/CXP4YR1MNRM/de/documents?0" },
              { label: "Evergabe Online", url: "https://www.evergabe-online.de/tenderdetails.html?id=12345" },
              { label: "DTVP Summary", url: "https://www.dtvp.de/Satellite/public/company/project/CXP4YR1MNRM/de/about" }
            ].map((preset) => (
              <button
                key={preset.label}
                type="button"
                onClick={() => setUrl(preset.url)}
                className="text-xs px-3 py-1.5 bg-white border border-slate-200 hover:border-indigo-400 hover:text-indigo-600 rounded-full font-bold shadow-sm transition-all active:scale-95 cursor-pointer"
                disabled={busy}
              >
                {preset.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* ── Agent Leaderboard ── */}
        <div className="lg:col-span-2 bg-white border border-slate-200/80 rounded-2xl shadow-sm overflow-hidden flex flex-col">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2 bg-slate-50/50">
            <Activity className="w-5 h-5 text-indigo-500" />
            <h2 className="font-extrabold text-slate-800">Agent Performance Leaderboard</h2>
          </div>
          <div className="overflow-x-auto overflow-y-auto max-h-[600px] flex-1 custom-scrollbar">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-500 border-b border-slate-100 sticky top-0 z-10">
                <tr>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider">Agent Engine</th>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Runs</th>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Accuracy</th>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Avg Steps</th>
                  <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-right">Cost</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(!finalSummary || finalSummary.length === 0) ? (
                  <tr>
                    <td colSpan={5} className="px-6 py-12 text-center text-slate-400 font-semibold">
                      No agent runs recorded yet. Trigger a session above.
                    </td>
                  </tr>
                ) : (
                  finalSummary.map((s: any) => (
                    <tr key={s.agent} className="hover:bg-slate-50/30 transition-colors">
                      <td className="px-6 py-4">
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-bold bg-indigo-50 border border-indigo-100 text-indigo-700 font-mono">
                          <Bot className="w-3.5 h-3.5" />
                          {s.agent}
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
                      <td className="px-6 py-4 text-center font-bold text-slate-500">{s.avg_steps}</td>
                      <td className="px-6 py-4 text-right font-bold text-slate-800">{usd(s.total_cost_usd)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* ── Recent Runs Feed ── */}
        <div className="bg-white border border-slate-200/80 rounded-2xl shadow-sm flex flex-col h-[500px]">
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
            <h2 className="font-extrabold text-slate-800 flex items-center gap-2">
              <Clock className="w-5 h-5 text-indigo-500" />
              Live Execution Feed
            </h2>
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
              {finalRuns.length} runs
            </span>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
            {(!finalRuns || finalRuns.length === 0) ? (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 space-y-2 py-8">
                <Bot className="w-10 h-10 opacity-20" />
                <p className="text-xs font-semibold">No recent activity.</p>
              </div>
            ) : (
              finalRuns.map((r: any) => (
                <div 
                  key={r.id} 
                  className="p-4 rounded-xl border border-slate-200 hover:border-slate-300 hover:bg-slate-50/50 transition-all flex flex-col gap-2.5"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className={`flex items-center gap-1.5 text-[11px] font-extrabold uppercase tracking-wide ${
                      r.success ? "text-emerald-700" : "text-rose-700"
                    }`}>
                      {r.success ? <CheckCircle2 className="w-4 h-4" /> : <XCircle className="w-4 h-4" />}
                      {r.success ? "Success" : "Failed"}
                    </div>
                    <span className="text-[10px] text-slate-400 flex items-center gap-1 font-mono font-bold">
                      <DollarSign className="w-3.5 h-3.5" />
                      {usd(r.cost_usd).replace("$", "")}
                    </span>
                  </div>
                  <div className="text-[11px] font-mono font-bold text-slate-500 truncate w-full" title={r.url}>
                    {r.url}
                  </div>
                  <div className="flex items-center gap-2 text-[10px] font-bold text-slate-400 mt-1 border-t border-slate-100/60 pt-2.5 flex-wrap">
                    <span className="bg-indigo-50 border border-indigo-100 text-indigo-700 px-2 py-0.5 rounded-md">{r.agent_name}</span>
                    <span className="bg-slate-100 px-2 py-0.5 rounded-md text-slate-600 flex items-center gap-1">
                      <Timer className="w-3 h-3" />
                      {r.steps} steps
                    </span>
                  </div>

                  {r.trace?.downloaded_files && r.trace.downloaded_files.length > 0 && (
                    <div className="mt-2 space-y-1.5 border-t border-slate-100/60 pt-2">
                      <div className="text-[10px] font-bold text-indigo-600 uppercase tracking-wider flex items-center gap-1">
                        <FileText className="w-3.5 h-3.5 text-indigo-500" />
                        Downloaded Files ({r.trace.downloaded_files.length})
                      </div>
                      <div className="space-y-1 max-h-[120px] overflow-y-auto custom-scrollbar pr-1">
                        {r.trace.downloaded_files.map((file: string, idx: number) => (
                          <div key={idx} className="flex items-center gap-1.5 p-1.5 px-2.5 bg-slate-50 border border-slate-100 rounded-xl text-[10px] font-bold text-slate-600 hover:bg-slate-100/80 transition-colors">
                            <span className="truncate w-full" title={file}>
                              {file}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
