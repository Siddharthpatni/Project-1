"use client";

import useSWR from "swr";
import { useParams, useRouter } from "next/navigation";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import Link from "next/link";
import { Download, FileText, AlertCircle, CheckCircle2, BadgeCheck, Loader2, ArrowLeft } from "lucide-react";
import { useState } from "react";

const STRATEGY_STYLES: Record<string, string> = {
  manual_scraper:         "bg-blue-100 text-blue-700",
  existing_scraper:       "bg-purple-100 text-purple-700",
  deterministic_template: "bg-emerald-100 text-emerald-700",
  llm_generated_scraper:  "bg-amber-100 text-amber-700",
  computer_use_agent:     "bg-rose-100 text-rose-700",
};

function StrategyBadge({ strategy }: { strategy: string }) {
  const cls = STRATEGY_STYLES[strategy] ?? "bg-slate-100 text-slate-600";
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {strategy.replace(/_/g, " ")}
    </span>
  );
}

function fileIcon(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "📄";
  if (["zip", "rar", "7z"].includes(ext)) return "🗜️";
  if (["doc", "docx"].includes(ext)) return "📝";
  if (["xls", "xlsx"].includes(ext)) return "📊";
  return "📎";
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [isZipping, setIsZipping] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const { data: job } = useSWR(id ? api(`/jobs/${id}`) : null, fetcher, { 
    refreshInterval: (data) => (!data || data.status === "pending" || data.status === "running") ? 2000 : 0 
  });
  const { data: documents } = useSWR(id ? api(`/jobs/${id}/documents`) : null, fetcher, { 
    refreshInterval: (data) => (job?.status === "pending" || job?.status === "running") ? 2000 : 0 
  });

  if (!job) return <p className="text-slate-500">Loading…</p>;

  const totalDocs = documents?.length ?? 0;

  const handleDownloadZip = async (e: React.MouseEvent) => {
    e.preventDefault();
    if (isZipping) return;
    setIsZipping(true);
    try {
      const response = await fetch(api(`/jobs/${id}/download-all`));
      if (!response.ok) throw new Error("Failed to generate ZIP");
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `job-${id?.slice(0, 8)}-documents.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error(err);
      alert("Failed to download ZIP. It might still be processing or there was an error.");
    } finally {
      setIsZipping(false);
    }
  };

  const handleDeleteJob = async () => {
    if (!confirm("Are you sure you want to delete this job? This action cannot be undone.")) return;
    setIsDeleting(true);
    try {
      const response = await fetch(api(`/jobs/${id}`), { method: 'DELETE' });
      if (!response.ok) throw new Error("Failed to delete job");
      router.push('/jobs');
    } catch (err) {
      console.error(err);
      alert("Failed to delete job.");
      setIsDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* ── Navigation / Back Button ── */}
      <div className="flex items-center gap-3 text-xs font-semibold text-slate-500">
        <Link href="/" className="hover:text-indigo-600 transition-colors">
          Dashboard
        </Link>
        <span className="text-slate-350">/</span>
        <Link href="/jobs" className="flex items-center gap-1 hover:text-indigo-600 transition-colors">
          <ArrowLeft className="w-3 h-3" />
          All Jobs
        </Link>
        <span className="text-slate-355 text-slate-300">/</span>
        <span className="text-slate-400 font-normal truncate max-w-[20ch]">Job {job.id.slice(0, 8)}</span>
      </div>

      <header className="border-b border-slate-100 pb-5">
        <div className="flex flex-wrap items-center justify-between gap-4 w-full">
          <div className="flex items-center gap-3">
            <h1 className="text-xl font-bold font-mono text-slate-800 bg-slate-100 px-3 py-1.5 rounded-lg border border-slate-200">{job.id}</h1>
            <button 
              onClick={() => {
                navigator.clipboard.writeText(job.id);
                alert("Copied Job ID!");
              }}
              className="text-xs px-2.5 py-1.5 bg-brand-50 hover:bg-brand-100 text-brand-700 font-semibold rounded-md border border-brand-200 transition"
            >
              Copy ID
            </button>
          </div>
          <button 
            onClick={handleDeleteJob}
            disabled={isDeleting}
            className="text-xs px-4 py-2 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 font-semibold rounded-lg transition disabled:opacity-50 shadow-sm"
          >
            {isDeleting ? "Deleting..." : "Delete Job"}
          </button>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-4 text-xs font-semibold text-slate-600">
          <StatusBadge status={job.status} />
          <span className="bg-slate-100 px-2.5 py-1 rounded text-slate-700">{job.completed}/{job.total_urls} URLs</span>
          <span className="flex items-center gap-1 bg-slate-100 px-2.5 py-1 rounded text-slate-700">
            <FileText className="w-3.5 h-3.5 text-brand-600" />
            {totalDocs} document{totalDocs !== 1 ? "s" : ""}
          </span>
          <span className="bg-slate-100 px-2.5 py-1 rounded text-slate-700">${(job.cost_usd ?? 0).toFixed(4)}</span>
          <span className="bg-slate-100 px-2.5 py-1 rounded text-slate-700">{new Date(job.created_at).toLocaleString()}</span>
        </div>
      </header>

      {/* Progress Bar */}
      {(job.status === "pending" || job.status === "running") && (
        <div className="card p-4 flex flex-col gap-2 border-brand-100 bg-brand-50/50">
          <div className="flex justify-between text-xs font-medium text-brand-700">
            <span>Scraping Progress</span>
            <span>{Math.round((job.completed / Math.max(1, job.total_urls)) * 100)}% ({job.completed}/{job.total_urls})</span>
          </div>
          <div className="w-full bg-brand-100/50 rounded-full h-2.5 overflow-hidden">
            <div 
              className="bg-brand-500 h-2.5 rounded-full transition-all duration-500 ease-out relative" 
              style={{ width: `${Math.max(5, (job.completed / Math.max(1, job.total_urls)) * 100)}%` }}
            >
              <div className="absolute top-0 left-0 bottom-0 right-0 animate-pulse bg-white/30"></div>
            </div>
          </div>
          <p className="text-[10px] text-brand-600/70 text-right mt-1 animate-pulse">Running agents...</p>
        </div>
      )}

      {/* ── Strategies ── */}
      <div className="card overflow-hidden border-2 border-slate-100 shadow-sm">
        <div className="px-5 py-4 border-b border-slate-100 bg-slate-50/50 flex items-center gap-2">
          <BadgeCheck className="w-5 h-5 text-brand-600" />
          <h2 className="font-semibold text-slate-800">Cascade Pipeline Paths</h2>
        </div>
        <div className="divide-y divide-slate-100">
          {job.items?.map((item: any) => {
            const strategyKeys = Object.keys(STRATEGY_STYLES);
            const targetIdx = item.strategy === "none" ? 5 : strategyKeys.indexOf(item.strategy);
            const isJobFailed = item.status === "failed";
            
            return (
              <div key={item.id} className="p-4">
                <div className="flex items-start justify-between">
                  <div className="text-xs font-mono text-slate-600 truncate max-w-[60ch] mt-1" title={item.url}>
                    {item.url.length > 60 ? item.url.slice(0, 60) + "..." : item.url}
                  </div>
                  <div className="flex flex-col items-end">
                    <div className="flex items-center gap-2 flex-wrap justify-end">
                      {strategyKeys.map((s, idx) => {
                        const isTried = isJobFailed || idx <= targetIdx;
                        if (!isTried) return null;
                        const isSuccess = s === item.strategy;
                        const isFailed = !isSuccess;
                        const cls = STRATEGY_STYLES[s];
                        return (
                          <div key={s} className="flex items-center gap-2">
                            {idx > 0 && <span className="text-slate-300">→</span>}
                            <div className={`flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${cls} ${isFailed ? "opacity-50" : "opacity-100"}`}>
                              {isSuccess && <CheckCircle2 className="w-3 h-3" />}
                              {isFailed && <div className="w-1.5 h-1.5 rounded-full bg-red-500" />}
                              {s.replace(/_/g, " ")}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    {item.strategy !== "none" && (
                      <div className="text-xs text-slate-500 mt-1">
                        └ {item.document_count} docs, {item.runtime_seconds?.toFixed(1)}s
                      </div>
                    )}
                  </div>
                </div>
                {item.error_message && (
                  <div className="mt-3 text-xs font-mono text-rose-600 bg-rose-50 p-2 rounded truncate max-w-full">
                    {item.error_message.slice(0, 200)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Downloaded Documents — shown first, prominently ── */}
      <div className="card overflow-hidden border-2 border-slate-100 shadow-sm">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
          <h2 className="font-semibold flex items-center gap-2">
            <Download className="w-4 h-4 text-brand-600" />
            Downloaded Documents
          </h2>
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500">{totalDocs} file{totalDocs !== 1 ? "s" : ""}</span>
            {totalDocs > 0 && (
              <button
                onClick={handleDownloadZip}
                disabled={isZipping}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 text-white text-xs font-medium rounded-lg hover:bg-slate-800 transition-colors disabled:opacity-70 disabled:cursor-not-allowed"
              >
                {isZipping ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Zipping...
                  </>
                ) : (
                  <>
                    <Download className="w-3.5 h-3.5" />
                    Download All as ZIP
                  </>
                )}
              </button>
            )}
          </div>
        </div>

        {(!documents || totalDocs === 0) ? (
          <div className="px-5 py-12 text-center text-slate-400 text-sm">
            {job.status === "running" || job.status === "pending"
              ? "Scraping in progress — documents will appear here as they are downloaded."
              : "No documents were downloaded for this job."}
          </div>
        ) : (
          <div className="divide-y divide-slate-100 max-h-[500px] overflow-y-auto">
            {documents.map((doc: any) => (
              <div key={doc.id} className="flex items-center justify-between px-5 py-3.5 hover:bg-slate-50/30 transition-colors">
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-xl flex-shrink-0">{fileIcon(doc.filename)}</span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-medium text-slate-800 truncate">{doc.filename}</p>
                      {(() => {
                        const ext = doc.filename.split('.').pop()?.toLowerCase() ?? "";
                        const isDoc = ["pdf", "zip", "docx", "xlsx", "doc", "xls", "ppt", "pptx", "rar", "7z"].includes(ext);
                        return isDoc ? (
                          <span title="Verified Document" className="flex items-center">
                            <BadgeCheck className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                          </span>
                        ) : (
                          <span title="Unknown Type" className="flex items-center">
                            <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0" />
                          </span>
                        );
                      })()}
                    </div>
                    <p className="text-xs text-slate-400">{formatBytes(doc.size_bytes)} · v{doc.version}</p>
                  </div>
                </div>
                {doc.download_url ? (
                  <a
                    href={api(doc.download_url)}
                    download={doc.filename}
                    className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 bg-brand-600 text-white text-xs font-medium rounded-lg hover:bg-brand-700 transition-colors ml-4"
                  >
                    <Download className="w-3.5 h-3.5" />
                    Download
                  </a>
                ) : (
                  <span className="text-slate-400 text-xs ml-4">Unavailable</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Per-URL breakdown ── */}
      <div className="card overflow-hidden border-2 border-slate-100 shadow-sm">
        <div className="px-5 py-4 border-b border-slate-100 bg-slate-50/50">
          <h2 className="font-semibold text-slate-800">URL Breakdown</h2>
        </div>
        <div className="overflow-x-auto overflow-y-auto max-h-[400px]">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-600 sticky top-0 z-10 shadow-sm">
            <tr>
              <th className="px-5 py-3 font-medium">URL</th>
              <th className="px-5 py-3 font-medium">Strategy</th>
              <th className="px-5 py-3 font-medium text-center">Iters</th>
              <th className="px-5 py-3 font-medium text-center">Runtime</th>
              <th className="px-5 py-3 font-medium text-center">Docs</th>
              <th className="px-5 py-3 font-medium text-right">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {job.items?.map((item: any) => (
              <tr key={item.id} className="hover:bg-slate-50/50 transition-colors">
                <td className="px-5 py-4 max-w-xs truncate font-mono text-xs text-slate-700" title={item.url}>{item.url}</td>
                <td className="px-5 py-4"><StrategyBadge strategy={item.strategy} /></td>
                <td className="px-5 py-4 text-center text-slate-600 font-semibold">{item.iterations}</td>
                <td className="px-5 py-4 text-center text-slate-600">{item.runtime_seconds?.toFixed(1)}s</td>
                <td className="px-5 py-4 text-center font-bold text-slate-800">{item.document_count}</td>
                <td className="px-5 py-4 text-right">
                  <div className="inline-flex justify-end w-full">
                    <StatusBadge status={item.status} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>

      {/* ── Errors ── */}
      {job.items?.some((i: any) => i.error_message) && (
        <div className="card p-6">
          <h2 className="text-sm font-semibold mb-3 flex items-center gap-2 text-rose-700">
            <AlertCircle className="w-4 h-4" />
            Errors
          </h2>
          <ul className="space-y-2 text-sm">
            {job.items.filter((i: any) => i.error_message).map((i: any) => (
              <li key={i.id} className="border-l-4 border-rose-300 pl-3">
                <div className="text-xs text-slate-500 font-mono truncate mb-0.5">{i.url}</div>
                <div className="text-xs text-rose-700">{i.error_message}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}