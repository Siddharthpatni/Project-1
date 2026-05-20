"use client";

import useSWR from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

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
      <h1 className="text-2xl font-bold">Jobs</h1>

      <div className="card overflow-x-auto overflow-y-auto max-h-[600px]">
        <table className="w-full text-sm">
          <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-600 sticky top-0 z-10 shadow-sm">
            <tr>
              <th className="px-4 py-3 font-medium">Job</th>
              <th className="px-4 py-3 font-medium">Created</th>
              <th className="px-4 py-3 font-medium">URLs</th>
              <th className="px-4 py-3 font-medium">Completed</th>
              <th className="px-4 py-3 font-medium">Cost</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-500">Loading…</td></tr>
            )}
            {jobs?.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-500">No jobs yet.</td></tr>
            )}
            {jobs?.map((j: any) => (
              <tr key={j.id} className="border-t border-slate-100 hover:bg-slate-50">
                <td className="px-4 py-3">
                  <Link href={`/jobs/${j.id}`} className="text-brand-700 hover:underline">
                    <JobLabel job={j} />
                  </Link>
                </td>
                <td className="px-4 py-3 text-slate-600">{new Date(j.created_at).toLocaleString()}</td>
                <td className="px-4 py-3">{j.total_urls}</td>
                <td className="px-4 py-3">{j.completed}</td>
                <td className="px-4 py-3">${(j.cost_usd ?? 0).toFixed(4)}</td>
                <td className="px-4 py-3"><StatusBadge status={j.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
