/**
 * Scraper Registry page — view and manage the Phase 3 reusable scraper cache.
 *
 * Every domain that has been successfully scraped by an LLM-generated or
 * manually-written scraper has an entry here. The registry is what allows
 * subsequent jobs for the same domain to skip code generation entirely
 * (the EXISTING strategy).
 *
 * Features:
 *   - Table of all scraper templates: domain, source (disk/llm/manual/cua),
 *     platform, success/failure counts, health rating
 *   - Code viewer modal: syntax-highlighted Python source
 *   - Download scraper as .py file
 *   - Delete scraper from registry
 *   - "Learn + Generate" panel: run route-learner then LLM-generate for a URL
 *
 * Data source: GET /api/scrapers (with success/failure counts from DB)
 */
"use client";

import useSWR from "swr";
import { api, fetcher, postJSON } from "@/lib/api";
import { Fragment, useState } from "react";
import { Loader2, Search, ArrowRight, FileText, CheckCircle2, XCircle, Layers, Compass, DollarSign, ListOrdered, ChevronRight, Cpu, CheckCircle } from "lucide-react";

/** Mobile card for one registry scraper — shown instead of the table on phones. */
function ScraperCard({ s }: { s: any }) {
  const total = s.success_count + s.failure_count;
  const rate = total ? Math.round((s.success_count / total) * 100) : 0;
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-xs font-bold break-all" style={{ color: "var(--fg)" }}>{s.domain}</span>
        <span className="badge bg-emerald-50 text-emerald-700 border-emerald-200 flex-shrink-0">{rate}%</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        <span className="badge bg-slate-100 text-slate-600 border-slate-200">{s.source}</span>
        {s.platform && <span className="badge bg-slate-100 text-slate-600 border-slate-200">{s.platform}</span>}
        {s.route_used && <span className="badge bg-emerald-50 text-emerald-700 border-emerald-200">route</span>}
        {s.cua_hint && <span className="badge bg-rose-50 text-rose-700 border-rose-200">CUA</span>}
      </div>
      <div className="flex items-center justify-between text-[11px] font-medium" style={{ color: "var(--fg-subtle)" }}>
        <span>{s.success_count} ok · {s.failure_count} fail</span>
        <span>{s.avg_runtime != null ? `${s.avg_runtime.toFixed(1)}s` : "—"}</span>
        <span>{new Date(s.created_at).toLocaleDateString()}</span>
      </div>
      {(s.code || s.cua_hint) && (
        <details className="text-xs">
          <summary className="cursor-pointer font-semibold" style={{ color: "var(--brand)" }}>View details</summary>
          {s.cua_hint && <pre className="mt-2 p-3 rounded-lg overflow-x-auto text-[10px] whitespace-pre-wrap custom-scrollbar" style={{ background: "#0d1117", color: "#e6edf3" }}>{s.cua_hint}</pre>}
          {s.code && <pre className="mt-2 p-3 rounded-lg overflow-x-auto text-[10px] custom-scrollbar" style={{ background: "#0d1117", color: "#e6edf3" }}>{s.code}</pre>}
        </details>
      )}
    </div>
  );
}

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
    <div className="space-y-8">
      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight flex items-center gap-3">
            <Search className="w-8 h-8 text-emerald-600" />
            Autonomous Scraper Registry
          </h1>
          <p className="text-slate-500 mt-1.5 text-sm sm:text-base font-medium">
            Generate and manage reusable domain-level scraper modules learn-promoted from real runs.
          </p>
        </div>
      </header>

      {/* Route Learning Card */}
      <div className="bg-white border-2 border-emerald-100 rounded-2xl p-6 md:p-8 shadow-sm bg-gradient-to-br from-emerald-50/20 via-white to-white space-y-6">
        <div className="flex items-center gap-4">
          <div className="p-3 bg-emerald-100/70 border border-emerald-200 rounded-2xl">
            <Compass className="w-6 h-6 text-emerald-700 animate-spin" style={{ animationDuration: '6s' }} />
          </div>
          <div>
            <h2 className="text-xl font-extrabold text-slate-900">Explore Route &amp; Compile Scraper</h2>
            <p className="text-xs text-slate-500 font-medium mt-0.5">
              Input a procurement notice URL to auto-explore document structures and generate reusable scrapers.
            </p>
          </div>
        </div>

        <div className="space-y-4">
          <div className="flex flex-col lg:flex-row gap-4">
            <div className="relative flex-1">
              <input
                type="url"
                value={learnUrl}
                onChange={(e) => setLearnUrl(e.target.value)}
                placeholder="https://www.evergabe-online.de/tenderdetails.html?id=..."
                className="w-full pl-4 pr-4 py-3 border border-slate-200 rounded-xl text-sm font-mono focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition-all shadow-sm"
                disabled={learning}
              />
            </div>
            <div className="flex gap-3">
              <select
                value={learnModel}
                onChange={(e) => setLearnModel(e.target.value)}
                className="px-4 py-3 border border-slate-200 rounded-xl text-sm font-semibold outline-none focus:ring-2 focus:ring-emerald-500 shadow-sm bg-white cursor-pointer min-w-[200px]"
                disabled={learning}
              >
                <option value="">Default AI Learner</option>
                <option value="google/gemini-2.5-flash">Gemini 2.5 Flash</option>
                <option value="google/gemini-2.5-pro">Gemini 2.5 Pro</option>
                <option value="openai/gpt-4o">GPT-4o</option>
                <option value="anthropic/claude-sonnet-4">Claude Sonnet 4</option>
              </select>

              <button
                onClick={startLearning}
                disabled={learning || !learnUrl.trim()}
                className="px-6 py-3 bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-400 text-white font-semibold rounded-xl transition-all shadow active:scale-[0.98] flex items-center gap-2 flex-shrink-0 cursor-pointer"
              >
                {learning ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Exploring...
                  </>
                ) : (
                  <>
                    <ArrowRight className="w-4 h-4" />
                    Compile Scraper
                  </>
                )}
              </button>
            </div>
          </div>

          <div className="text-xs text-slate-400 font-medium">
            💡 The AI agent will spawn a sandboxed visual session to trace links and record clicks. Compilation takes ~30-60s.
          </div>
        </div>

        {/* Result */}
        {learnResult && (
          <div className="p-6 bg-slate-50/70 border border-slate-200 rounded-2xl space-y-4 animate-in fade-in slide-in-from-bottom-2 duration-300">
            <div className="flex flex-wrap items-center gap-2 text-slate-800 font-extrabold">
              <CheckCircle2 className="w-5 h-5 text-emerald-600" />
              Scraper Generated for <span className="font-mono text-sm px-2 py-0.5 bg-white rounded border text-indigo-700">{learnResult.domain}</span>
              {learnResult.platform && (
                <span className="px-2.5 py-0.5 bg-slate-200 text-slate-700 text-xs rounded-full font-mono font-bold shadow-sm">
                  {learnResult.platform}
                </span>
              )}
              {learnResult.status === "generated_and_saved" && (!learnResult.route_map?.steps || learnResult.route_map.steps.length === 0) && (
                <span className="px-2.5 py-0.5 bg-emerald-100 text-emerald-800 text-xs rounded-full font-bold shadow-sm">
                  Deterministic Match
                </span>
              )}
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-100">
                <div className="text-slate-400 font-bold text-xs uppercase tracking-wider flex items-center gap-1">
                  <FileText className="w-3.5 h-3.5 text-indigo-500" /> Documents Listed
                </div>
                <div className="text-2xl font-extrabold text-slate-800 mt-1">{learnResult.documents_found}</div>
              </div>
              <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-100">
                <div className="text-slate-400 font-bold text-xs uppercase tracking-wider flex items-center gap-1">
                  <ListOrdered className="w-3.5 h-3.5 text-indigo-500" /> Route Clicks
                </div>
                <div className="text-2xl font-extrabold text-slate-800 mt-1">{learnResult.route_map?.steps?.length || 0}</div>
              </div>
              <div className="bg-white p-4 rounded-xl shadow-sm border border-slate-100">
                <div className="text-slate-400 font-bold text-xs uppercase tracking-wider flex items-center gap-1">
                  <DollarSign className="w-3.5 h-3.5 text-emerald-500" /> LLM Cost
                </div>
                <div className="text-2xl font-extrabold text-emerald-700 mt-1">${(learnResult.cost_usd || 0).toFixed(4)}</div>
              </div>
            </div>

            {/* Route Steps */}
            {learnResult.route_map?.steps?.length > 0 && (
              <details className="text-xs group border border-slate-200 rounded-xl bg-white p-3.5 shadow-sm">
                <summary className="cursor-pointer font-bold text-indigo-600 hover:text-indigo-700 select-none flex items-center gap-1.5">
                  <span className="transition-transform group-open:rotate-90"><ChevronRight className="w-4 h-4" /></span>
                  View Discovered Actions ({learnResult.route_map.steps.length} steps)
                </summary>
                <div className="mt-3 space-y-2.5">
                  {learnResult.route_map.steps.map((step: any, i: number) => (
                    <div key={i} className="flex items-start gap-3 p-3 bg-slate-50 rounded-lg border border-slate-100 hover:border-slate-200 transition-colors">
                      <span className="px-2 py-0.5 bg-slate-200 text-slate-700 rounded-md text-[10px] font-bold font-mono uppercase flex-shrink-0">
                        {step.action}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="text-slate-755 font-semibold leading-relaxed">{step.description}</div>
                        {step.selector && (
                          <div className="text-slate-400 font-mono mt-0.5 select-all truncate">{step.selector}</div>
                        )}
                        {step.found_downloads?.length > 0 && (
                          <div className="text-emerald-600 font-bold flex items-center gap-1 mt-1">
                            <CheckCircle className="w-3.5 h-3.5" />
                            {step.found_downloads.length} tender file(s) matched
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </details>
            )}

            {/* Generated Code */}
            <details className="text-xs group border border-slate-200 rounded-xl bg-white p-3.5 shadow-sm">
              <summary className="cursor-pointer font-bold text-indigo-600 hover:text-indigo-700 select-none flex items-center gap-1.5">
                <span className="transition-transform group-open:rotate-90"><ChevronRight className="w-4 h-4" /></span>
                View Generated Python Scraper Script
              </summary>
              <div className="mt-3 p-4 bg-slate-900 text-slate-100 rounded-xl overflow-x-auto max-h-96 custom-scrollbar shadow-inner border border-slate-800">
                <pre className="font-mono leading-relaxed text-[11px]">{learnResult.scraper_code}</pre>
              </div>
            </details>
          </div>
        )}

        {/* Error */}
        {learnError && (
          <div className="p-4 bg-rose-50 border border-rose-200 rounded-2xl flex items-start gap-3 animate-shake">
            <XCircle className="w-5 h-5 text-rose-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="text-sm font-bold text-rose-800">Scraper Compilation Failed</p>
              <p className="text-xs text-rose-600 font-semibold mt-0.5">{learnError}</p>
            </div>
          </div>
        )}
      </div>

      {/* Existing Scrapers — mobile cards */}
      <div className="md:hidden space-y-3">
        {scrapers?.length === 0 && (
          <div className="card p-8 text-center text-sm" style={{ color: "var(--fg-subtle)" }}>
            Registry is empty. Run a compilation above to build your first template.
          </div>
        )}
        {scrapers?.map((s: any) => <ScraperCard key={s.id} s={s} />)}
      </div>

      {/* Existing Scrapers Table (desktop) */}
      <div className="bg-white border border-slate-200/80 rounded-2xl shadow-sm overflow-hidden hidden md:block">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center gap-2.5 bg-slate-50/50">
          <Layers className="w-5 h-5 text-slate-600" />
          <h2 className="font-bold text-slate-800">Generated Procurement Scrapers</h2>
        </div>
        <div className="overflow-y-auto max-h-[600px] custom-scrollbar">
          <table className="w-full text-sm table-fixed">
            <colgroup>
              <col className="w-[22%]" />
              <col className="w-[12%]" />
              <col className="w-[14%]" />
              <col className="w-[10%]" />
              <col className="w-[18%]" />
              <col className="w-[10%]" />
              <col className="w-[14%]" />
            </colgroup>
            <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-500 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
              <tr>
                <th className="px-4 py-3 font-bold text-xs uppercase tracking-wider">Domain</th>
                <th className="px-4 py-3 font-bold text-xs uppercase tracking-wider">Source</th>
                <th className="px-4 py-3 font-bold text-xs uppercase tracking-wider">Platform</th>
                <th className="px-4 py-3 font-bold text-xs uppercase tracking-wider text-center">Flags</th>
                <th className="px-4 py-3 font-bold text-xs uppercase tracking-wider text-center">Success Rate</th>
                <th className="px-4 py-3 font-bold text-xs uppercase tracking-wider text-center">Runtime</th>
                <th className="px-4 py-3 font-bold text-xs uppercase tracking-wider text-right">Created</th>
              </tr>
            </thead>
            <tbody>
              {scrapers?.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-slate-400 font-semibold">
                    Registry is empty. Run a compilation above to build your first template.
                  </td>
                </tr>
              )}
              {scrapers?.map((s: any) => {
                const total = s.success_count + s.failure_count;
                const rate = total ? Math.round((s.success_count / total) * 100) : 0;
                return (
                  <Fragment key={s.id}>
                    <tr className="border-t border-slate-100 hover:bg-slate-50/30 transition-colors">
                      <td className="px-4 py-3">
                        <span title={s.domain} className="block font-mono text-xs font-bold text-slate-700 truncate">{s.domain}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-block px-2 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wider border ${
                          s.source === 'llm'           ? 'bg-purple-50 text-purple-700 border-purple-100' :
                          s.source === 'deterministic' ? 'bg-emerald-50 text-emerald-700 border-emerald-100' :
                          s.source === 'disk'          ? 'bg-amber-50 text-amber-700 border-amber-200' :
                          s.source === 'cua'           ? 'bg-rose-50 text-rose-700 border-rose-100' :
                          'bg-blue-50 text-blue-700 border-blue-100'
                        }`}>
                          {s.source === 'disk' ? '💾 disk' : s.source}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs font-bold text-slate-500 truncate">
                        {s.platform ?? <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <div className="flex items-center justify-center gap-1.5">
                          {s.route_used && (
                            <span title="Route-guided" className="inline-flex items-center justify-center w-5 h-5 bg-emerald-50 border border-emerald-200 text-emerald-700 text-[10px] font-extrabold rounded-full">✓</span>
                          )}
                          {s.cua_hint && (
                            <span title="CUA interaction trace available" className="inline-flex items-center gap-0.5 px-1.5 py-0.5 bg-rose-50 border border-rose-200 text-rose-700 text-[10px] font-extrabold rounded-full">
                              <Cpu className="w-2.5 h-2.5"/>CUA
                            </span>
                          )}
                          {!s.route_used && !s.cua_hint && <span className="text-slate-300 font-medium">—</span>}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-center">
                        <div className="flex flex-col items-center gap-0.5">
                          <span className="text-xs font-bold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-100 whitespace-nowrap">
                            {rate}% ({s.success_count} ok)
                          </span>
                          {s.failure_count > 0 && (
                            <span className="text-[10px] font-bold text-rose-500">{s.failure_count} fail</span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-center font-bold text-slate-600 text-xs">
                        {s.avg_runtime != null ? `${s.avg_runtime.toFixed(1)}s` : <span className="text-slate-300">—</span>}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-400 text-xs font-medium">
                        {new Date(s.created_at).toLocaleDateString()}
                      </td>
                    </tr>
                    {(s.code || s.cua_hint) && (
                      <tr className="bg-slate-50/30 border-b border-slate-100">
                        <td colSpan={7} className="px-4 py-3 space-y-2">
                          {s.cua_hint && (
                            <details className="text-xs group border border-rose-100 rounded-xl bg-white p-3 shadow-inner">
                              <summary className="cursor-pointer font-bold text-rose-600 hover:text-rose-700 select-none flex items-center gap-1.5 active:scale-95 transition-transform">
                                <span className="group-open:hidden">▶</span><span className="hidden group-open:inline">▼</span>
                                <Cpu className="w-3.5 h-3.5"/>CUA Interaction Trace <span className="font-normal text-rose-400 ml-1">(used to guide LLM generation)</span>
                              </summary>
                              <div className="mt-3 p-4 bg-slate-950 text-slate-200 rounded-xl overflow-x-auto max-h-64 custom-scrollbar shadow-inner border border-slate-800">
                                <pre className="font-mono leading-relaxed text-[11px] whitespace-pre-wrap">{s.cua_hint}</pre>
                              </div>
                            </details>
                          )}
                          {s.code && (
                            <details className="text-xs group border border-slate-100 rounded-xl bg-white p-3 shadow-inner">
                              <summary className="cursor-pointer font-bold text-indigo-600 hover:text-indigo-700 select-none flex items-center gap-1 active:scale-95 transition-transform">
                                <span className="group-open:hidden">▶</span><span className="hidden group-open:inline">▼</span> View Template Python Code
                              </summary>
                              <div className="mt-3 p-4 bg-slate-900 text-slate-100 rounded-xl overflow-x-auto shadow-inner border border-slate-800">
                                <pre className="font-mono leading-relaxed text-[11px]">{s.code}</pre>
                              </div>
                            </details>
                          )}
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
