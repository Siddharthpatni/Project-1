"use client";

import useSWR from "swr";
import { api, fetcher, postJSON } from "@/lib/api";
import { Fragment, useState } from "react";
import Link from "next/link";
import { Loader2, Search, ArrowRight, FileText, CheckCircle2, XCircle, ArrowLeft } from "lucide-react";

export default function ScrapersPage() {
  const { data: scrapers, mutate } = useSWR(api("/scrapers"), fetcher, { refreshInterval: 8000 });

  // Route learning state
  const [learnUrl, setLearnUrl] = useState("");
  const [learnModel, setLearnModel] = useState("");
  const [learning, setLearning] = useState(false);
  const [learnResult, setLearnResult] = useState<any>(null);
  const [learnError, setLearnError] = useState<string | null>(null);

  async function startLearning() {
    if (!learnUrl.trim()) return;
    setLearning(true);
    setLearnResult(null);
    setLearnError(null);
    try {
      const body: any = { url: learnUrl.trim() };
      if (learnModel) body.model = learnModel;
      const result = await postJSON("/scrapers/learn", body);
      setLearnResult(result);
      mutate(); // refresh the scrapers list
    } catch (e: any) {
      setLearnError(e?.message || "Route learning failed");
    } finally {
      setLearning(false);
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
            <Search className="w-6 h-6 text-brand-600" />
            Phase 3 — Scraper Registry
          </h1>
          <p className="text-slate-600 text-sm mt-1">
            Reusable scrapers keyed by domain. Auto-promoted from successful Phase 1 runs.
          </p>
        </div>
      </header>

      {/* Route Learning Card */}
      <div className="card p-6 border-2 border-dashed border-emerald-200 bg-gradient-to-br from-emerald-50/50 to-white">
        <div className="flex items-center gap-3 mb-4">
          <div className="p-2 bg-emerald-100 rounded-lg">
            <Search className="w-5 h-5 text-emerald-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-emerald-950">Learn Route &amp; Generate Scraper</h2>
            <p className="text-xs text-slate-500">
              Visit a URL, discover the path to documents, and auto-generate a fast scraper.
            </p>
          </div>
        </div>

        <div className="space-y-3">
          <div className="flex gap-3">
            <input
              type="url"
              value={learnUrl}
              onChange={(e) => setLearnUrl(e.target.value)}
              placeholder="https://www.evergabe-online.de/tenderdetails.html?id=..."
              className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition-all shadow-sm"
              disabled={learning}
            />
            <select
              value={learnModel}
              onChange={(e) => setLearnModel(e.target.value)}
              className="px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-emerald-500 min-w-[180px] shadow-sm bg-white"
              disabled={learning}
            >
              <option value="">Default model</option>
              <option value="google/gemini-2.5-flash">Gemini 2.5 Flash</option>
              <option value="google/gemini-2.5-flash-lite">Gemini 2.5 Flash Lite</option>
              <option value="anthropic/claude-sonnet-4.5">Claude 3.5 Sonnet</option>
              <option value="openai/gpt-4o">GPT-4o</option>
              <option value="openai/gpt-4o-mini">GPT-4o Mini</option>
            </select>
          </div>

          <div className="flex items-center justify-between mt-2">
            <p className="text-xs text-slate-400 max-w-lg">
              The system will open a headless browser, explore the page, and record the exact
              click-path to documents. This usually takes 30–60 seconds.
            </p>
            <button
              onClick={startLearning}
              disabled={learning || !learnUrl.trim()}
              className="px-6 py-2.5 bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-400 text-white font-medium rounded-lg transition-colors shadow-sm flex items-center gap-2"
            >
              {learning ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"/>
                  Learning route…
                </>
              ) : (
                <>
                  <ArrowRight className="w-4 h-4" />
                  Learn &amp; Generate
                </>
              )}
            </button>
          </div>
        </div>

        {/* Result */}
        {learnResult && (
          <div className="mt-4 p-4 bg-emerald-50 border border-emerald-200 rounded-lg space-y-3">
            <div className="flex items-center gap-2 text-emerald-700 font-medium">
              <CheckCircle2 className="w-5 h-5" />
              Scraper generated for <span className="font-mono text-sm">{learnResult.domain}</span>
              {learnResult.platform && (
                <span className="ml-2 px-2 py-0.5 bg-slate-200 text-slate-700 text-xs rounded-full font-mono shadow-sm">
                  {learnResult.platform}
                </span>
              )}
              {learnResult.status === "generated_and_saved" && (!learnResult.route_map?.steps || learnResult.route_map.steps.length === 0) && (
                <span className="ml-2 px-2 py-0.5 bg-emerald-200 text-emerald-800 text-xs rounded-full shadow-sm">
                  Deterministic
                </span>
              )}
            </div>

            <div className="grid grid-cols-3 gap-4 text-sm">
              <div className="bg-white p-3 rounded-md shadow-sm">
                <div className="text-slate-500 text-xs">Documents Found</div>
                <div className="text-2xl font-bold text-emerald-700">{learnResult.documents_found}</div>
              </div>
              <div className="bg-white p-3 rounded-md shadow-sm">
                <div className="text-slate-500 text-xs">Route Steps</div>
                <div className="text-2xl font-bold text-brand-700">{learnResult.route_map?.steps?.length || 0}</div>
              </div>
              <div className="bg-white p-3 rounded-md shadow-sm">
                <div className="text-slate-500 text-xs">LLM Cost</div>
                <div className="text-2xl font-bold text-slate-700">${(learnResult.cost_usd || 0).toFixed(4)}</div>
              </div>
            </div>

            {/* Route Steps */}
            {learnResult.route_map?.steps?.length > 0 && (
              <details className="text-xs">
                <summary className="cursor-pointer font-medium text-brand-600 hover:text-brand-700 select-none">
                  View Discovered Route ({learnResult.route_map.steps.length} steps)
                </summary>
                <div className="mt-2 space-y-1">
                  {learnResult.route_map.steps.map((step: any, i: number) => (
                    <div key={i} className="flex items-start gap-2 p-2 bg-white rounded border border-slate-100">
                      <span className="px-1.5 py-0.5 bg-slate-200 text-slate-700 rounded text-[10px] font-mono uppercase flex-shrink-0">
                        {step.action}
                      </span>
                      <div className="min-w-0">
                        <div className="text-slate-700 truncate">{step.description}</div>
                        {step.selector && (
                          <div className="text-slate-400 font-mono truncate">{step.selector}</div>
                        )}
                        {step.found_downloads?.length > 0 && (
                          <div className="text-emerald-600 flex items-center gap-1 mt-0.5">
                            <FileText className="w-3 h-3" />
                            {step.found_downloads.length} document(s) found
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            )}

            {/* Generated Code */}
            <details className="text-xs">
              <summary className="cursor-pointer font-medium text-brand-600 hover:text-brand-700 select-none">
                View Generated Scraper Code
              </summary>
              <div className="mt-2 p-3 bg-slate-900 text-slate-50 rounded-md overflow-x-auto max-h-96">
                <pre className="font-mono leading-relaxed text-xs">{learnResult.scraper_code}</pre>
              </div>
            </details>
          </div>
        )}

        {/* Error */}
        {learnError && (
          <div className="mt-4 p-4 bg-rose-50 border border-rose-200 rounded-lg flex items-start gap-2">
            <XCircle className="w-5 h-5 text-rose-500 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-rose-700">{learnError}</div>
          </div>
        )}
      </div>

      {/* Existing Scrapers Table */}
      <div className="card overflow-hidden flex flex-col">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2">
          <FileText className="w-5 h-5 text-slate-500" />
          <h2 className="font-semibold text-slate-800">Generated Registry</h2>
        </div>
        <div className="overflow-x-auto overflow-y-auto max-h-[600px]">
          <table className="w-full text-sm">
            <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-600 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
              <tr>
                <th className="px-5 py-3 font-medium">Domain</th>
                <th className="px-5 py-3 font-medium">Source</th>
                <th className="px-5 py-3 font-medium">Platform</th>
                <th className="px-5 py-3 font-medium text-center">Route</th>
                <th className="px-5 py-3 font-medium text-center">Successes</th>
                <th className="px-5 py-3 font-medium text-center">Failures</th>
                <th className="px-5 py-3 font-medium text-center">Avg Runtime</th>
                <th className="px-5 py-3 font-medium text-right">Created</th>
              </tr>
            </thead>
            <tbody>
              {scrapers?.length === 0 && (
                <tr><td colSpan={8} className="px-5 py-12 text-center text-slate-400">Registry is empty.</td></tr>
              )}
              {scrapers?.map((s: any) => {
                const total = s.success_count + s.failure_count;
                const rate = total ? Math.round((s.success_count / total) * 100) : 0;
                return (
                  <Fragment key={s.id}>
                    <tr className="border-t border-slate-100 hover:bg-slate-50/50 transition-colors">
                      <td className="px-5 py-4 font-mono text-xs font-semibold text-slate-700">{s.domain}</td>
                      <td className="px-5 py-4">
                        <span className={`px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                          s.source === 'llm' ? 'bg-purple-100 text-purple-700' :
                          s.source === 'deterministic' ? 'bg-emerald-100 text-emerald-700' :
                          'bg-blue-100 text-blue-700'
                        }`}>
                          {s.source}
                        </span>
                      </td>
                      <td className="px-5 py-4 font-mono text-xs text-slate-500">
                        {s.platform ?? <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-5 py-4 text-center">
                        {s.route_used
                          ? <span title="Route-guided" className="text-emerald-600 font-bold">✓</span>
                          : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-5 py-4 text-center text-emerald-700 font-medium">{s.success_count} <span className="text-[10px] text-emerald-500">({rate}%)</span></td>
                      <td className="px-5 py-4 text-center text-rose-700">{s.failure_count}</td>
                      <td className="px-5 py-4 text-center text-slate-600">{s.avg_runtime?.toFixed(1)}s</td>
                      <td className="px-5 py-4 text-right text-slate-500 text-xs">{new Date(s.created_at).toLocaleDateString()}</td>
                    </tr>
                    {s.code && (
                      <tr className="border-b border-slate-200 bg-slate-50/50">
                        <td colSpan={8} className="px-5 py-3">
                          <details className="text-xs group">
                            <summary className="cursor-pointer font-medium text-indigo-600 hover:text-indigo-700 select-none flex items-center gap-1">
                              <span className="group-open:hidden">▶</span><span className="hidden group-open:inline">▼</span> View Scraper Code
                            </summary>
                            <div className="mt-3 p-4 bg-[#1e1e1e] text-[#d4d4d4] rounded-lg overflow-x-auto shadow-inner border border-[#333]">
                              <pre className="font-mono leading-relaxed text-[11px]">{s.code}</pre>
                            </div>
                          </details>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
