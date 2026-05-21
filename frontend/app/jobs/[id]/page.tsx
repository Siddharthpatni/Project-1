"use client";

import useSWR from "swr";
import { useParams, useRouter } from "next/navigation";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import Link from "next/link";
import { Download, FileText, AlertCircle, CheckCircle2, BadgeCheck, Loader2, ArrowLeft, Trash2, Copy, Cpu, Clock, DollarSign, Layers } from "lucide-react";
import { useState } from "react";

const STRATEGY_STYLES: Record<string, string> = {
  manual_scraper:         "bg-blue-50 text-blue-700 border-blue-200",
  existing_scraper:       "bg-purple-50 text-purple-700 border-purple-200",
  deterministic_template: "bg-emerald-50 text-emerald-700 border-emerald-200",
  llm_generated_scraper:  "bg-amber-50 text-amber-700 border-amber-200",
  computer_use_agent:     "bg-rose-50 text-rose-700 border-rose-200",
};

const STRATEGY_NAMES: Record<string, string> = {
  manual_scraper:         "Deterministic Core Scraper",
  existing_scraper:       "Cached Registry Scraper",
  deterministic_template: "Autonomous Discovered Scraper",
  llm_generated_scraper:  "Visual Route Exploration Scraper",
  computer_use_agent:     "Intelligent CUA Browser Agent",
};

function StrategyBadge({ strategy }: { strategy: string }) {
  const cls = STRATEGY_STYLES[strategy] ?? "bg-slate-50 text-slate-655 border-slate-200";
  const name = STRATEGY_NAMES[strategy] ?? strategy.replace(/_/g, " ");
  return (
    <span className={`px-2.5 py-1 rounded-full text-xs font-bold border ${cls}`}>
      {name}
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

function fileBadgeColor(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return "bg-rose-50 border-rose-100 text-rose-700";
  if (["zip", "rar", "7z"].includes(ext)) return "bg-amber-50 border-amber-100 text-amber-700";
  if (["doc", "docx"].includes(ext)) return "bg-blue-50 border-blue-100 text-blue-700";
  if (["xls", "xlsx"].includes(ext)) return "bg-emerald-50 border-emerald-100 text-emerald-700";
  return "bg-slate-50 border-slate-100 text-slate-700";
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

  if (!job) return <p className="text-slate-500 max-w-7xl mx-auto px-4 py-8">Loading task detail log...</p>;

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
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
      {/* ── Navigation / Back Button ── */}
      <div className="flex flex-wrap items-center gap-3 text-xs font-semibold text-slate-500">
        <Link href="/" className="hover:text-indigo-650 transition-colors">
          Dashboard
        </Link>
        <span className="text-slate-300">/</span>
        <Link href="/jobs" className="flex items-center gap-1 hover:text-indigo-650 transition-all hover:translate-x-[-1px]">
          <ArrowLeft className="w-3.5 h-3.5" />
          All Jobs
        </Link>
        <span className="text-slate-300">/</span>
        <span className="text-slate-400 font-normal truncate max-w-[20ch]">Job {job.id.slice(0, 8)}</span>
      </div>

      <header className="border-b border-slate-100 pb-5 space-y-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 w-full">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-lg sm:text-xl font-bold font-mono text-slate-800 bg-slate-100 px-4 py-2 rounded-xl border border-slate-200 shadow-inner">
              {job.id}
            </h1>
            <button 
              onClick={() => {
                navigator.clipboard.writeText(job.id);
                alert("Copied Job ID!");
              }}
              className="text-xs px-3 py-2 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 font-bold rounded-xl border border-indigo-150 transition active:scale-95 flex items-center gap-1.5 cursor-pointer"
            >
              <Copy className="w-3.5 h-3.5" />
              Copy ID
            </button>
          </div>
          <button 
            onClick={handleDeleteJob}
            disabled={isDeleting}
            className="text-xs px-4 py-2 bg-rose-50 hover:bg-rose-100 text-rose-700 border border-rose-200 font-bold rounded-xl transition disabled:opacity-50 shadow-sm flex items-center gap-1.5 cursor-pointer active:scale-95"
          >
            <Trash2 className="w-3.5 h-3.5" />
            {isDeleting ? "Deleting..." : "Delete Job"}
          </button>
        </div>

        {/* Header Stats Chips */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex">
            <StatusBadge status={job.status} />
          </div>
          <span className="bg-slate-100 border border-slate-200/60 px-3 py-1.5 rounded-xl text-xs font-bold text-slate-700 flex items-center gap-1.5">
            <Layers className="w-4 h-4 text-slate-500" /> {job.completed}/{job.total_urls} URLs
          </span>
          <span className="bg-slate-100 border border-slate-200/60 px-3 py-1.5 rounded-xl text-xs font-bold text-slate-700 flex items-center gap-1.5">
            <FileText className="w-4 h-4 text-indigo-500" /> {totalDocs} document{totalDocs !== 1 ? "s" : ""}
          </span>
          <span className="bg-slate-100 border border-slate-200/60 px-3 py-1.5 rounded-xl text-xs font-bold text-slate-700 flex items-center gap-1.5">
            <DollarSign className="w-4 h-4 text-emerald-500" /> ${(job.cost_usd ?? 0).toFixed(4)}
          </span>
          <span className="bg-slate-100 border border-slate-200/60 px-3 py-1.5 rounded-xl text-xs font-bold text-slate-700 flex items-center gap-1.5">
            <Clock className="w-4 h-4 text-slate-500" /> {new Date(job.created_at).toLocaleString()}
          </span>
        </div>
      </header>

      {/* Progress Bar */}
      {(job.status === "pending" || job.status === "running") && (
        <div className="p-5 border border-indigo-100 bg-indigo-50/40 rounded-2xl space-y-2">
          <div className="flex justify-between text-xs font-bold text-indigo-750">
            <span>Retrieving Documents Pipeline...</span>
            <span>{Math.round((job.completed / Math.max(1, job.total_urls)) * 100)}% ({job.completed}/{job.total_urls})</span>
          </div>
          <div className="w-full bg-indigo-100/50 rounded-full h-3 overflow-hidden">
            <div 
              className="bg-indigo-650 h-3 rounded-full transition-all duration-500 ease-out relative" 
              style={{ width: `${Math.max(5, (job.completed / Math.max(1, job.total_urls)) * 100)}%` }}
            >
              <div className="absolute top-0 left-0 bottom-0 right-0 animate-pulse bg-white/20"></div>
            </div>
          </div>
          <p className="text-[10px] text-indigo-600/70 text-right mt-1.5 animate-pulse font-semibold">Cascade agent workers currently running...</p>
        </div>
      )}

      {/* ── Strategies / Execution Path Cascade ── */}
      <div className="bg-white border border-slate-250/80 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50 flex items-center gap-2">
          <BadgeCheck className="w-5 h-5 text-indigo-600" />
          <h2 className="font-extrabold text-slate-800">Cascade Strategy Execution Paths</h2>
        </div>
        <div className="divide-y divide-slate-150">
          {job.items?.map((item: any) => {
            const strategyKeys = ["manual_scraper", "existing_scraper", "deterministic_template", "llm_generated_scraper", "computer_use_agent"];
            const targetIdx = item.strategy === "none" ? -1 : strategyKeys.indexOf(item.strategy);
            const isJobFailed = item.status === "failed";
            
            return (
              <div key={item.id} className="p-6 space-y-4 hover:bg-slate-50/10 transition-colors">
                <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                  <div className="min-w-0 flex-1">
                    <div className="text-xs font-bold text-slate-400 font-mono tracking-wider uppercase">Source URL Target</div>
                    <div className="text-xs font-bold font-mono text-indigo-700 break-all select-all mt-1 bg-slate-50 border border-slate-150 p-2.5 rounded-lg w-full" title={item.url}>
                      {item.url}
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 lg:justify-end">
                    {strategyKeys.map((s, idx) => {
                      const isTried = isJobFailed || idx <= targetIdx || (targetIdx === -1 && idx === 0);
                      if (!isTried) return null;
                      const isSuccess = s === item.strategy;
                      const cls = STRATEGY_STYLES[s] ?? "bg-slate-50 text-slate-600 border-slate-200";
                      
                      return (
                        <div key={s} className="flex items-center gap-1.5">
                          {idx > 0 && <span className="text-slate-300 font-bold">→</span>}
                          <div className={`flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold uppercase border ${cls} ${!isSuccess && isTried && !isJobFailed ? "opacity-40" : "opacity-100"}`}>
                            {isSuccess ? (
                              <CheckCircle2 className="w-3 h-3 text-emerald-600 flex-shrink-0" />
                            ) : (
                              <div className="w-1.5 h-1.5 rounded-full bg-rose-500 flex-shrink-0" />
                            )}
                            {s.replace(/_/g, " ").replace("scraper", "")}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-4 text-xs font-bold text-slate-550 border-t border-slate-100 pt-3">
                  {item.strategy !== "none" && (
                    <>
                      <span className="text-emerald-700 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded-md">
                        Downloaded Docs: {item.document_count}
                      </span>
                      <span className="text-indigo-700 bg-indigo-50 border border-indigo-100 px-2 py-0.5 rounded-md">
                        Total Time: {item.runtime_seconds?.toFixed(1)}s
                      </span>
                      <span className="text-slate-650 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-md">
                        Iterations: {item.iterations}
                      </span>
                    </>
                  )}
                  <span className="ml-auto">
                    <StatusBadge status={item.status} />
                  </span>
                </div>

                {item.error_message && (
                  <div className="text-xs font-bold font-mono text-rose-600 bg-rose-50/50 border border-rose-100 p-3 rounded-xl max-w-full leading-relaxed select-all">
                    🚨 {item.error_message}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ── Downloaded Documents ── */}
      <div className="bg-white border border-slate-250/80 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 flex flex-wrap items-center justify-between gap-4 bg-slate-50/50">
          <h2 className="font-extrabold flex items-center gap-2 text-slate-800">
            <Download className="w-4 h-4 text-indigo-650" />
            Scraped Tender Packages &amp; PDFs
          </h2>
          <div className="flex items-center gap-3">
            <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">{totalDocs} files</span>
            {totalDocs > 0 && (
              <button
                onClick={handleDownloadZip}
                disabled={isZipping}
                className="flex items-center gap-1.5 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold rounded-xl transition-all shadow-sm active:scale-95 disabled:opacity-70 disabled:cursor-not-allowed cursor-pointer"
              >
                {isZipping ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Zipping...
                  </>
                ) : (
                  <>
                    <Download className="w-3.5 h-3.5" />
                    Download All ZIP
                  </>
                )}
              </button>
            )}
          </div>
        </div>

        {(!documents || totalDocs === 0) ? (
          <div className="px-6 py-12 text-center text-slate-400 text-sm font-semibold">
            {job.status === "running" || job.status === "pending"
              ? "Scraping in progress — documents will appear here as they are downloaded."
              : "No documents were downloaded for this job."}
          </div>
        ) : (
          <div className="divide-y divide-slate-100 max-h-[500px] overflow-y-auto custom-scrollbar">
            {documents.map((doc: any) => (
              <div key={doc.id} className="flex items-center justify-between px-6 py-4 hover:bg-slate-50/30 transition-colors gap-4">
                <div className="flex items-center gap-3.5 min-w-0">
                  <span className={`text-xl p-2.5 rounded-xl border flex-shrink-0 ${fileBadgeColor(doc.filename)}`}>
                    {fileIcon(doc.filename)}
                  </span>
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <p className="text-sm font-bold text-slate-800 truncate" title={doc.filename}>{doc.filename}</p>
                      {(() => {
                        const ext = doc.filename.split('.').pop()?.toLowerCase() ?? "";
                        const isDoc = ["pdf", "zip", "docx", "xlsx", "doc", "xls", "ppt", "pptx", "rar", "7z"].includes(ext);
                        return isDoc ? (
                          <span title="Verified Document Archive" className="flex items-center">
                            <BadgeCheck className="w-4 h-4 text-emerald-600 flex-shrink-0" />
                          </span>
                        ) : (
                          <span title="Unknown Extension" className="flex items-center">
                            <AlertCircle className="w-4 h-4 text-amber-500 flex-shrink-0" />
                          </span>
                        );
                      })()}
                    </div>
                    <p className="text-xs font-bold text-slate-400 mt-0.5">{formatBytes(doc.size_bytes)} · version {doc.version}</p>
                  </div>
                </div>
                {doc.download_url ? (
                  <a
                    href={api(doc.download_url)}
                    download={doc.filename}
                    className="flex-shrink-0 flex items-center gap-1.5 px-4 py-2 bg-slate-100 hover:bg-slate-200 border border-slate-200 text-slate-700 text-xs font-bold rounded-xl transition-all shadow-sm active:scale-95 ml-4 cursor-pointer"
                  >
                    <Download className="w-3.5 h-3.5 text-slate-500" />
                    Download
                  </a>
                ) : (
                  <span className="text-slate-400 text-xs font-bold ml-4">Unavailable</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Per-URL Breakdown Table ── */}
      <div className="bg-white border border-slate-250/80 rounded-2xl shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-slate-100 bg-slate-50/50">
          <h2 className="font-extrabold text-slate-800">Cascade Run History Breakdown</h2>
        </div>
        <div className="overflow-x-auto overflow-y-auto max-h-[400px] custom-scrollbar">
          <table className="w-full text-sm">
            <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-500 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
              <tr>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider">URL</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider">Resolved Strategy</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Iterations</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Runtime</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Documents</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-right">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-150">
              {job.items?.map((item: any) => (
                <tr key={item.id} className="hover:bg-slate-50/30 transition-colors">
                  <td className="px-6 py-4 max-w-xs truncate font-mono text-xs font-bold text-slate-700" title={item.url}>
                    {item.url}
                  </td>
                  <td className="px-6 py-4"><StrategyBadge strategy={item.strategy} /></td>
                  <td className="px-6 py-4 text-center text-slate-655 font-bold">{item.iterations}</td>
                  <td className="px-6 py-4 text-center font-semibold text-slate-600">{item.runtime_seconds?.toFixed(1)}s</td>
                  <td className="px-6 py-4 text-center font-extrabold text-slate-800">{item.document_count}</td>
                  <td className="px-6 py-4 text-right">
                    <div className="inline-flex justify-end">
                      <StatusBadge status={item.status} />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}