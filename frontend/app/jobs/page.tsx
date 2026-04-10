"use client";

import useSWR from "swr";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

export default function JobsPage() {
  const { data: jobs, isLoading } = useSWR(api("/jobs"), fetcher, { refreshInterval: 4000 });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Jobs</h1>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-3 font-medium">Job ID</th>
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
                <td className="px-4 py-3 font-mono text-xs">
                  <Link href={`/jobs/${j.id}`} className="text-brand-700 hover:underline">
                    {j.id.slice(0, 8)}…
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
