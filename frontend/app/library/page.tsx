"use client";

import useSWR from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import { Download, FileText, Code2, Globe, FolderArchive, AlertCircle, Layers, Calendar, Cpu, CheckCircle } from "lucide-react";

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function fileIcon(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "📄";
  if (["zip", "rar", "7z"].includes(ext)) return "🗜️";
  if (["doc", "docx"].includes(ext)) return "📝";
  if (["xls", "xlsx"].includes(ext)) return "📊";
  return "📎";
}

function fileBadgeColor(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "bg-rose-50 border-rose-200 text-rose-700";
  if (["zip", "rar", "7z"].includes(ext)) return "bg-amber-50 border-amber-200 text-amber-700";
  if (["doc", "docx"].includes(ext)) return "bg-blue-50 border-blue-200 text-blue-700";
  if (["xls", "xlsx"].includes(ext)) return "bg-emerald-50 border-emerald-200 text-emerald-700";
  return "bg-slate-50 border-slate-200 text-slate-700";
}

function sourceColor(source: string) {
  if (source === "llm") return "bg-purple-50 text-purple-700 border-purple-100";
  if (source === "deterministic") return "bg-emerald-50 text-emerald-700 border-emerald-100";
  return "bg-blue-50 text-blue-700 border-blue-100";
}

export default function LibraryPage() {
  const { data: scrapers } = useSWR(api("/scrapers"), fetcher, { refreshInterval: 10000 });
  const { data: localFiles } = useSWR(api("/jobs/local-files"), fetcher, { refreshInterval: 10000 });

  // Group local files by domain
  const filesByDomain: Record<string, any[]> = {};
  for (const f of localFiles ?? []) {
    const key = f.domain || "unknown";
    if (!filesByDomain[key]) filesByDomain[key] = [];
    filesByDomain[key].push(f);
  }
  const domainKeys = Object.keys(filesByDomain).sort();

  return (
    <div className="space-y-8">

      <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Library &amp; Artifact Repository
          </h1>
          <p className="text-slate-500 mt-1.5 text-sm sm:text-base font-medium">
            Access downloaded documents and active scraper modules grouped by source domain.
          </p>
        </div>
      </header>

      {/* ── Downloaded Files by Domain ── */}
      <section className="space-y-4">
        <div className="flex items-center gap-2">
          <Layers className="w-5 h-5 text-indigo-600" />
          <h2 className="text-lg font-bold text-slate-800">Downloaded Procurement Files</h2>
        </div>

        {domainKeys.length === 0 ? (
          <div className="card p-12 text-center text-slate-400 text-sm border-2 border-dashed border-slate-200 rounded-2xl bg-slate-50/50 shadow-inner">
            <AlertCircle className="w-10 h-10 mx-auto mb-3 text-slate-300" />
            <p className="font-semibold text-slate-500 text-base">No locally stored files found</p>
            <p className="text-xs text-slate-400 mt-1 max-w-md mx-auto">
              Scraping runs that complete successfully will list documents and packages here once retrieved.
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {domainKeys.map((domain) => (
              <div 
                key={domain} 
                className="bg-white border border-slate-200/80 rounded-2xl shadow-sm hover:shadow-md transition-all duration-300 flex flex-col h-[380px] overflow-hidden"
              >
                <div className="px-5 py-4 border-b border-slate-100 flex items-center gap-2.5 bg-slate-50/70">
                  <Globe className="w-4 h-4 text-slate-500" />
                  <span className="font-mono text-sm font-bold text-slate-700 truncate">{domain}</span>
                  <span className="ml-auto text-[11px] font-bold text-indigo-600 bg-indigo-50 px-2.5 py-1 rounded-full border border-indigo-100">
                    {filesByDomain[domain].length} file{filesByDomain[domain].length !== 1 ? "s" : ""}
                  </span>
                </div>
                <div className="divide-y divide-slate-100 overflow-y-auto flex-1 custom-scrollbar">
                  {filesByDomain[domain].map((f: any, idx: number) => (
                    <div 
                      key={idx} 
                      className="flex items-center justify-between px-5 py-4 hover:bg-slate-50/60 transition-colors gap-4"
                    >
                      <div className="flex items-center gap-3.5 min-w-0">
                        <span className={`text-xl p-2 rounded-xl border flex-shrink-0 ${fileBadgeColor(f.filename)}`}>
                          {fileIcon(f.filename)}
                        </span>
                        <div className="min-w-0">
                          <p className="text-sm font-semibold text-slate-800 truncate" title={f.filename}>
                            {f.filename}
                          </p>
                          <p className="text-xs text-slate-400 font-bold mt-0.5">
                            {formatBytes(f.size_bytes)}
                          </p>
                        </div>
                      </div>
                      <a
                        href={api(f.download_url)}
                        download={f.filename}
                        className="flex-shrink-0 flex items-center gap-1.5 px-4 py-2 bg-indigo-600 text-white text-xs font-semibold rounded-xl hover:bg-indigo-700 transition-all shadow-sm active:scale-95 cursor-pointer hover:shadow"
                      >
                        <Download className="w-3.5 h-3.5" />
                        Download
                      </a>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── Scraper Code Library ── */}
      <section className="space-y-4 pt-4">
        <div className="flex items-center gap-2">
          <Code2 className="w-5 h-5 text-indigo-600" />
          <h2 className="text-lg font-bold text-slate-800">Scraper Template Codebase</h2>
        </div>

        {!scrapers || scrapers.length === 0 ? (
          <div className="card p-12 text-center text-slate-400 text-sm border-2 border-dashed border-slate-200 rounded-2xl bg-slate-50/50 shadow-inner">
            <AlertCircle className="w-10 h-10 mx-auto mb-3 text-slate-300" />
            <p className="font-semibold text-slate-500 text-base">No scraper templates in registry</p>
            <p className="text-xs text-slate-400 mt-1">
              Navigate to the <Link href="/scrapers" className="text-indigo-600 hover:underline font-bold">Scrapers</Link> tab to learn and auto-generate new scraper plugins.
            </p>
          </div>
        ) : (
          <div className="bg-white border border-slate-200/80 rounded-2xl shadow-sm overflow-hidden">
            <div className="overflow-x-auto overflow-y-auto max-h-[600px] custom-scrollbar">
              <table className="w-full text-sm">
                <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-500 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
                  <tr>
                    <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider">Domain</th>
                    <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider">Source</th>
                    <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider">Platform</th>
                    <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Success Rate</th>
                    <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider"><span className="flex items-center gap-1.5"><Calendar className="w-3.5 h-3.5" /> Created</span></th>
                    <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {scrapers.map((s: any) => (
                    <tr key={s.id} className="hover:bg-slate-50/40 transition-colors">
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2.5">
                          <Globe className="w-4 h-4 text-indigo-500 flex-shrink-0" />
                          <span className="font-mono text-xs font-bold text-slate-800">{s.domain}</span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <span className={`px-2.5 py-1 rounded-full text-xs font-bold border ${sourceColor(s.source)}`}>
                          {s.source}
                        </span>
                      </td>
                      <td className="px-6 py-4 font-mono text-xs font-bold text-slate-600">
                        {s.platform ?? <span className="text-slate-350">—</span>}
                      </td>
                      <td className="px-6 py-4 text-center">
                        <span className="inline-flex items-center gap-1 text-xs font-bold text-emerald-700 bg-emerald-50 px-2.5 py-1 rounded-full border border-emerald-100">
                          <CheckCircle className="w-3 h-3" />
                          {s.success_count} runs
                        </span>
                      </td>
                      <td className="px-6 py-4 text-slate-500 font-medium">
                        {new Date(s.created_at).toLocaleDateString(undefined, {
                          year: 'numeric',
                          month: 'short',
                          day: 'numeric'
                        })}
                      </td>
                      <td className="px-6 py-4 text-right">
                        <div className="flex items-center gap-3.5 justify-end">
                          <details className="relative">
                            <summary className="cursor-pointer text-xs text-indigo-600 hover:text-indigo-700 font-bold select-none list-none flex items-center gap-1 active:scale-95 transition-transform">
                              <FileText className="w-3.5 h-3.5" />
                              View Code
                            </summary>
                            <div className="absolute right-0 top-6 z-20 w-[600px] max-h-80 overflow-auto bg-slate-900 text-slate-100 rounded-xl shadow-2xl border border-slate-800 p-4 text-left custom-scrollbar">
                              <div className="flex justify-between items-center pb-2 mb-2 border-b border-slate-850">
                                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest font-mono">Python Code Block</span>
                                <span className="text-[10px] font-bold text-indigo-400 font-mono">{s.domain}</span>
                              </div>
                              <pre className="font-mono text-xs leading-relaxed whitespace-pre-wrap">{s.code}</pre>
                            </div>
                          </details>
                          <a
                            href={api(`/scrapers/${s.id}/download`)}
                            download={`scraper_${s.domain.replace(/\./g, "_")}.py`}
                            className="flex items-center gap-1 text-xs text-slate-650 hover:text-slate-900 font-bold transition-colors border border-slate-200 hover:border-slate-350 bg-white shadow-sm px-2.5 py-1.5 rounded-lg active:scale-95"
                            title="Download .py file"
                          >
                            <Download className="w-3.5 h-3.5 text-slate-500" />
                            .py
                          </a>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
