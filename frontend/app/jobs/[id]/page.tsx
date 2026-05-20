"use client";

import useSWR from "swr";
import { useParams } from "next/navigation";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import { Download, FileText, AlertCircle, CheckCircle2, BadgeCheck } from "lucide-react";

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
  const { data: job } = useSWR(id ? api(`/jobs/${id}`) : null, fetcher, { 
    refreshInterval: (data) => (!data || data.status === "pending" || data.status === "running") ? 2000 : 0 
  });
  const { data: documents } = useSWR(id ? api(`/jobs/${id}/documents`) : null, fetcher, { 
    refreshInterval: (data) => (job?.status === "pending" || job?.status === "running") ? 2000 : 0 
  });

  if (!job) return <p className="text-slate-500">Loading…</p>;

  const totalDocs = documents?.length ?? 0;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold font-mono">{job.id}</h1>
        <div className="mt-2 flex items-center gap-3 text-sm text-slate-600">
          <StatusBadge status={job.status} />
          <span>{job.completed}/{job.total_urls} URLs</span>
          <span className="flex items-center gap-1">
            <FileText className="w-3.5 h-3.5" />
            {totalDocs} document{totalDocs !== 1 ? "s" : ""}
          </span>
          <span>${(job.cost_usd ?? 0).toFixed(4)}</span>
          <span>{new Date(job.created_at).toLocaleString()}</span>
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
      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100">
          <h2 className="font-semibold">Strategien</h2>
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
      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100 flex items-center justify-between">
          <h2 className="font-semibold flex items-center gap-2">
            <Download className="w-4 h-4 text-brand-600" />
            Downloaded Documents
          </h2>
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500">{totalDocs} file{totalDocs !== 1 ? "s" : ""}</span>
            {totalDocs > 0 && (
              <a
                href={api(`/jobs/${id}/download-all`)}
                download={`job-${id?.slice(0, 8)}-documents.zip`}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-700 text-white text-xs font-medium rounded-lg hover:bg-slate-800 transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                Download All as ZIP
              </a>
            )}
          </div>
        </div>

        {(!documents || totalDocs === 0) ? (
          <div className="px-4 py-8 text-center text-slate-400 text-sm">
            {job.status === "running" || job.status === "pending"
              ? "Scraping in progress — documents will appear here as they are downloaded."
              : "No documents were downloaded for this job."}
          </div>
        ) : (
          <div className="divide-y divide-slate-100">
            {documents.map((doc: any) => (
              <div key={doc.id} className="flex items-center justify-between px-4 py-3 hover:bg-slate-50 transition-colors">
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
      <div className="card overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-100">
          <h2 className="font-semibold">URL Breakdown</h2>
        </div>
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-3 font-medium">URL</th>
              <th className="px-4 py-3 font-medium">Strategy</th>
              <th className="px-4 py-3 font-medium">Iters</th>
              <th className="px-4 py-3 font-medium">Runtime</th>
              <th className="px-4 py-3 font-medium">Docs</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {job.items?.map((item: any) => (
              <tr key={item.id} className="border-t border-slate-100">
                <td className="px-4 py-3 max-w-xs truncate font-mono text-xs" title={item.url}>{item.url}</td>
                <td className="px-4 py-3"><StrategyBadge strategy={item.strategy} /></td>
                <td className="px-4 py-3 text-slate-600">{item.iterations}</td>
                <td className="px-4 py-3 text-slate-600">{item.runtime_seconds?.toFixed(1)}s</td>
                <td className="px-4 py-3 font-medium">{item.document_count}</td>
                <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
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