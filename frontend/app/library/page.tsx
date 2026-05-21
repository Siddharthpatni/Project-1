"use client";

import useSWR from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import { Download, FileText, Code2, Globe, FolderArchive, AlertCircle, ArrowLeft } from "lucide-react";

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

function sourceColor(source: string) {
  if (source === "llm") return "bg-purple-100 text-purple-700";
  if (source === "deterministic") return "bg-emerald-100 text-emerald-700";
  return "bg-blue-100 text-blue-700";
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
    <div className="space-y-6">
      {/* ── Navigation / Back Button ── */}
      <Link href="/" className="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-500 hover:text-indigo-600 transition-colors">
        <ArrowLeft className="w-3.5 h-3.5" />
        Back to Dashboard
      </Link>

      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2 text-slate-900">
            <FolderArchive className="w-6 h-6 text-brand-600" />
            Library
          </h1>
          <p className="text-slate-600 mt-1 text-sm">
            All downloaded files (ZIPs, PDFs) and generated scraper code, organized by domain.
          </p>
        </div>
      </header>

      {/* ── Downloaded Files by Domain ── */}
      <section>
        <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
          <FolderArchive className="w-5 h-5 text-brand-600" />
          Downloaded Files
        </h2>

        {domainKeys.length === 0 ? (
          <div className="card p-12 text-center text-slate-400 text-sm border-2 border-dashed border-slate-200">
            <AlertCircle className="w-8 h-8 mx-auto mb-2 text-slate-300" />
            No locally stored files found. Files appear here when S3 is unavailable or after scraping completes.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {domainKeys.map((domain) => (
              <div key={domain} className="card overflow-hidden border-2 border-slate-100 shadow-sm hover:shadow transition-shadow flex flex-col h-[320px]">
                <div className="px-4 py-3 border-b border-slate-100 flex items-center gap-2 bg-slate-50/50">
                  <Globe className="w-4 h-4 text-brand-500" />
                  <span className="font-mono text-sm font-semibold text-slate-700">{domain}</span>
                  <span className="ml-auto text-xs font-semibold text-brand-600 bg-brand-50 px-2 py-0.5 rounded-full">
                    {filesByDomain[domain].length} file{filesByDomain[domain].length !== 1 ? "s" : ""}
                  </span>
                </div>
                <div className="divide-y divide-slate-100 overflow-y-auto flex-1">
                  {filesByDomain[domain].map((f: any, idx: number) => (
                    <div key={idx} className="flex items-center justify-between px-4 py-3 hover:bg-slate-50/50 transition-colors">
                      <div className="flex items-center gap-3 min-w-0">
                        <span className="text-xl flex-shrink-0">{fileIcon(f.filename)}</span>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-slate-800 truncate" title={f.filename}>{f.filename}</p>
                          <p className="text-xs text-slate-400 font-medium">{formatBytes(f.size_bytes)}</p>
                        </div>
                      </div>
                      <a
                        href={api(f.download_url)}
                        download={f.filename}
                        className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 transition-colors ml-4 shadow-sm"
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
      <section>
        <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
          <Code2 className="w-5 h-5 text-brand-600" />
          Scraper Code
        </h2>

        {!scrapers || scrapers.length === 0 ? (
          <div className="card p-12 text-center text-slate-400 text-sm border-2 border-dashed border-slate-200">
            <AlertCircle className="w-8 h-8 mx-auto mb-2 text-slate-300" />
            No scrapers in registry yet. Generate scrapers from the{" "}
            <Link href="/scrapers" className="text-brand-600 hover:underline font-semibold">Scrapers</Link> page.
          </div>
        ) : (
          <div className="card overflow-hidden border-2 border-slate-100 shadow-sm">
            <div className="overflow-x-auto overflow-y-auto max-h-[600px]">
            <table className="w-full text-sm">
              <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-600 sticky top-0 z-10 shadow-sm">
                <tr>
                  <th className="px-5 py-3 font-medium">Domain</th>
                  <th className="px-5 py-3 font-medium">Source</th>
                  <th className="px-5 py-3 font-medium">Platform</th>
                  <th className="px-5 py-3 font-medium text-center">Successes</th>
                  <th className="px-5 py-3 font-medium">Created</th>
                  <th className="px-5 py-3 font-medium text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {scrapers.map((s: any) => (
                  <tr key={s.id} className="hover:bg-slate-50/50 transition-colors">
                    <td className="px-5 py-4">
                      <div className="flex items-center gap-2">
                        <Globe className="w-4 h-4 text-brand-500 flex-shrink-0" />
                        <span className="font-mono text-xs font-semibold text-slate-800">{s.domain}</span>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-semibold ${sourceColor(s.source)}`}>
                        {s.source}
                      </span>
                    </td>
                    <td className="px-5 py-4 font-mono text-xs text-slate-600">
                      {s.platform ?? <span className="text-slate-300">—</span>}
                    </td>
                    <td className="px-5 py-4 text-center text-emerald-700 font-semibold">{s.success_count}</td>
                    <td className="px-5 py-4 text-slate-600">{new Date(s.created_at).toLocaleDateString()}</td>
                    <td className="px-5 py-4 text-right">
                      <div className="flex items-center gap-3 justify-end">
                        <details className="relative">
                          <summary className="cursor-pointer text-xs text-brand-600 hover:text-brand-700 font-semibold select-none list-none flex items-center gap-1">
                            <FileText className="w-3.5 h-3.5" />
                            View
                          </summary>
                          <div className="absolute right-0 top-6 z-10 w-[500px] max-h-72 overflow-auto bg-slate-900 text-slate-50 rounded-lg shadow-xl border border-slate-700 p-3 text-left">
                            <pre className="font-mono text-xs leading-relaxed whitespace-pre-wrap">{s.code}</pre>
                          </div>
                        </details>
                        <a
                          href={api(`/scrapers/${s.id}/download`)}
                          download={`scraper_${s.domain.replace(/\./g, "_")}.py`}
                          className="flex items-center gap-1 text-xs text-slate-600 hover:text-slate-900 font-semibold transition-colors"
                          title="Download .py file"
                        >
                          <Download className="w-3.5 h-3.5" />
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
