"use client";

import useSWR from "swr";
import { api, fetcher, postJSON } from "@/lib/api";
import { Fragment, useState } from "react";
import { Loader2, Search, ArrowRight, FileText, CheckCircle2, XCircle } from "lucide-react";

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
      <header>
        <h1 className="text-2xl font-bold">Scraper Registry</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Phase 3: reusable scrapers keyed by domain. Auto-promoted from successful Phase 1 runs.
        </p>
      </header>

      {/* Route Learning Card */}
      <div className="card p-6 border-2 border-dashed border-brand-200 bg-gradient-to-br from-brand-50 to-white">
        <div className="flex items-center gap-2 mb-4">
          <div className="p-2 bg-brand-100 rounded-lg">
            <Search className="w-5 h-5 text-brand-600" />
          </div>
          <div>
            <h2 className="text-lg font-semibold">Learn Route &amp; Generate Scraper</h2>
            <p className="text-xs text-slate-500">
              Visit a URL, discover the path to documents, and auto-generate a scraper for the domain.
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
              className="flex-1 px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none transition-all"
              disabled={learning}
            />
            <select
              value={learnModel}
              onChange={(e) => setLearnModel(e.target.value)}
              className="px-3 py-2 border border-slate-300 rounded-lg text-sm outline-none focus:ring-2 focus:ring-brand-500 min-w-[180px]"
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

          <div className="flex items-center justify-between">
            <p className="text-xs text-slate-400">
              The system will open a headless browser, explore the page, and record the exact
              click-path to documents. This takes 30–60 seconds.
            </p>
            <button
              onClick={startLearning}
              disabled={learning || !learnUrl.trim()}
              className="btn-primary px-5 flex items-center gap-2 disabled:opacity-50"
            >
              {learning ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
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
      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-3 font-medium">Domain</th>
              <th className="px-4 py-3 font-medium">Source</th>
              <th className="px-4 py-3 font-medium">Platform</th>
              <th className="px-4 py-3 font-medium">Route</th>
              <th className="px-4 py-3 font-medium">Successes</th>
              <th className="px-4 py-3 font-medium">Failures</th>
              <th className="px-4 py-3 font-medium">Avg runtime</th>
              <th className="px-4 py-3 font-medium">Created</th>
            </tr>
          </thead>
          <tbody>
            {scrapers?.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-6 text-center text-slate-500">Registry is empty.</td></tr>
            )}
            {scrapers?.map((s: any) => {
              const total = s.success_count + s.failure_count;
              const rate = total ? Math.round((s.success_count / total) * 100) : 0;
              return (
                <Fragment key={s.id}>
                  <tr className="border-t border-slate-100">
                    <td className="px-4 py-3 font-mono text-xs">{s.domain}</td>
                    <td className="px-4 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${
                        s.source === 'llm' ? 'bg-purple-100 text-purple-700' :
                        s.source === 'deterministic' ? 'bg-emerald-100 text-emerald-700' :
                        'bg-blue-100 text-blue-700'
                      }`}>
                        {s.source}
                      </span>
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-500">
                      {s.platform ?? <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {s.route_used
                        ? <span title="Route-guided" className="text-emerald-600 font-bold">✓</span>
                        : <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-4 py-3 text-emerald-700">{s.success_count} ({rate}%)</td>
                    <td className="px-4 py-3 text-rose-700">{s.failure_count}</td>
                    <td className="px-4 py-3">{s.avg_runtime?.toFixed(1)}s</td>
                    <td className="px-4 py-3 text-slate-600">{new Date(s.created_at).toLocaleDateString()}</td>
                  </tr>
                  {s.code && (
                    <tr className="border-b border-slate-100 bg-slate-50">
                      <td colSpan={8} className="px-4 py-3">
                        <details className="text-xs">
                          <summary className="cursor-pointer font-medium text-brand-600 hover:text-brand-700 select-none">
                            View Scraper Code
                          </summary>
                          <div className="mt-2 p-3 bg-slate-900 text-slate-50 rounded-md overflow-x-auto">
                            <pre className="font-mono leading-relaxed">{s.code}</pre>
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
  );
}
