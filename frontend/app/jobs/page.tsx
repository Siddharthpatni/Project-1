"use client";

import useSWR from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import { Activity, ArrowLeft } from "lucide-react";

function JobLabel({ job }: { job: any }) {
  return (
    <div className="flex flex-col gap-1 w-full">
      {job.domains?.length > 0 ? (
        <div>
          <div className="font-medium text-slate-800 truncate max-w-[28ch]" title={job.domains.join(", ")}>
            {job.domains.slice(0, 2).join(", ")}{job.domains.length > 2 ? ` +${job.domains.length - 2}` : ""}
          </div>
          <div className="text-[10px] font-mono text-slate-400">{job.id.slice(0, 8)}…</div>
        </div>
      ) : (
        <span className="font-mono text-xs text-slate-600">{job.id.slice(0, 8)}…</span>
      )}
      
      {(job.status === "pending" || job.status === "running") && job.total_urls > 0 && (
        <div className="w-full max-w-[120px] bg-slate-100 rounded-full h-1 mt-1 overflow-hidden">
          <div 
            className="bg-brand-500 h-1 rounded-full transition-all duration-300"
            style={{ width: `${Math.max(5, (job.completed / job.total_urls) * 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}

export default function JobsPage() {
  const { data: jobs, isLoading } = useSWR(api("/jobs"), fetcher, { 
    refreshInterval: (data) => {
      if (!data) return 4000;
      const hasActive = data.some((j: any) => j.status === "pending" || j.status === "running");
      return hasActive ? 3000 : 0;
    }
  });

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
            <Activity className="w-6 h-6 text-brand-600 animate-pulse" />
            Jobs
          </h1>
          <p className="text-slate-600 mt-1 text-sm">
            Monitor active, completed, and pending tender document scraping tasks.
          </p>
        </div>
        {jobs && (
          <span className="text-xs font-semibold text-brand-600 bg-brand-50 px-3 py-1 rounded-full border border-brand-100">
            Total {jobs.length} jobs
          </span>
        )}
      </header>

      <div className="card overflow-hidden border-2 border-slate-100 shadow-sm">
        <div className="overflow-x-auto overflow-y-auto max-h-[600px]">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-600 sticky top-0 z-10 shadow-sm">
            <tr>
              <th className="px-5 py-3 font-medium">Job</th>
              <th className="px-5 py-3 font-medium">Created</th>
              <th className="px-5 py-3 font-medium text-center">URLs</th>
              <th className="px-5 py-3 font-medium text-center">Completed</th>
              <th className="px-5 py-3 font-medium text-center">Cost</th>
              <th className="px-5 py-3 font-medium text-right">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {isLoading && (
              <tr><td colSpan={6} className="px-5 py-12 text-center text-slate-500">Loading jobs…</td></tr>
            )}
            {jobs?.length === 0 && (
              <tr><td colSpan={6} className="px-5 py-12 text-center text-slate-500">No scraping jobs started yet.</td></tr>
            )}
            {jobs?.map((j: any) => (
              <tr key={j.id} className="hover:bg-slate-50/50 transition-colors">
                <td className="px-5 py-4">
                  <Link href={`/jobs/${j.id}`} className="text-brand-700 hover:text-brand-800 transition-colors">
                    <JobLabel job={j} />
                  </Link>
                </td>
                <td className="px-5 py-4 text-slate-600 font-medium">
                  {new Date(j.created_at).toLocaleString()}
                </td>
                <td className="px-5 py-4 text-center font-semibold text-slate-800">{j.total_urls}</td>
                <td className="px-5 py-4 text-center font-semibold text-slate-800">{j.completed}</td>
                <td className="px-5 py-4 text-center font-medium text-slate-600">${(j.cost_usd ?? 0).toFixed(4)}</td>
                <td className="px-5 py-4 text-right">
                  <div className="inline-flex justify-end w-full">
                    <StatusBadge status={j.status} />
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
