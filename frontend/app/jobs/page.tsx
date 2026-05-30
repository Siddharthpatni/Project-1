"use client";

import useSWR from "swr";
import { useState, useMemo } from "react";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import { Activity, Search, FolderCheck, Compass, DollarSign, ArrowRight, FileStack } from "lucide-react";

/* ── Skeleton row ──────────────────────────────────────────────────── */
function SkeletonRow() {
  return (
    <tr className="border-b border-slate-100">
      {[1, 2, 3, 4, 5, 6, 7].map((i) => (
        <td key={i} className="px-6 py-4">
          <div className="skeleton h-4 rounded w-3/4" />
        </td>
      ))}
    </tr>
  );
}

/* ── Job label ─────────────────────────────────────────────────────── */
function JobLabel({ job }: { job: any }) {
  return (
    <div className="flex flex-col gap-1">
      {job.domains?.length > 0 ? (
        <>
          <span
            className="font-semibold text-slate-800 truncate max-w-[28ch] text-sm"
            title={job.domains.join(", ")}
          >
            {job.domains.slice(0, 2).join(", ")}
            {job.domains.length > 2 && (
              <span className="text-slate-400 font-normal"> +{job.domains.length - 2}</span>
            )}
          </span>
          <span className="font-mono text-[10px] text-slate-400">{job.id.slice(0, 8)}…</span>
        </>
      ) : (
        <span className="font-mono text-xs font-semibold text-slate-700">{job.id.slice(0, 8)}…</span>
      )}

      {(job.status === "pending" || job.status === "running") && job.total_urls > 0 && (
        <div className="w-32 bg-slate-100 rounded-full h-1 mt-1 overflow-hidden">
          <div
            className="bg-indigo-500 h-1 rounded-full transition-all duration-500"
            style={{ width: `${Math.max(4, (job.completed / job.total_urls) * 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}

/* ── Page ──────────────────────────────────────────────────────────── */
export default function JobsPage() {
  const { data: jobs, isLoading } = useSWR(api("/jobs"), fetcher, {
    refreshInterval: (data) => {
      if (!data) return 4000;
      const hasActive = data.some((j: any) => j.status === "pending" || j.status === "running");
      return hasActive ? 3000 : 0;
    },
  });

  const [search, setSearch]           = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const metrics = useMemo(() => {
    if (!jobs || !jobs.length) return { active: 0, successRate: 0, totalCost: 0 };
    let active = 0, completed = 0, successful = 0, totalCost = 0;
    for (const j of jobs) {
      if (j.status === "pending" || j.status === "running") active++;
      else {
        completed++;
        if (j.status === "success" || j.status === "completed") successful++;
      }
      totalCost += j.cost_usd ?? 0;
    }
    return { active, successRate: completed ? Math.round((successful / completed) * 100) : 100, totalCost };
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    if (!jobs) return [];
    return jobs.filter((j: any) => {
      const matchSearch =
        (j.domains || []).some((d: string) => d.toLowerCase().includes(search.toLowerCase())) ||
        j.id.toLowerCase().includes(search.toLowerCase());
      if (!matchSearch) return false;
      if (statusFilter === "active")    return j.status === "pending" || j.status === "running";
      if (statusFilter === "completed") return j.status === "success" || j.status === "completed";
      if (statusFilter === "failed")    return j.status === "failed";
      return true;
    });
  }, [jobs, search, statusFilter]);

  const filterOptions = [
    { value: "all",       label: "All",       count: jobs?.length ?? 0 },
    { value: "active",    label: "Active",    count: metrics.active },
    { value: "completed", label: "Completed", count: jobs?.filter((j: any) => j.status === "success" || j.status === "completed").length ?? 0 },
    { value: "failed",    label: "Failed",    count: jobs?.filter((j: any) => j.status === "failed").length ?? 0 },
  ];

  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">

      {/* ── Header ── */}
      <header className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight flex items-center gap-3">
            <Activity className="w-7 h-7 text-indigo-600" />
            Jobs
          </h1>
          <p className="text-slate-500 mt-1 text-sm font-medium">
            Monitor active and historical document retrieval jobs.
          </p>
        </div>
        <Link href="/" className="btn-primary text-sm self-start sm:self-auto">
          + New Job
        </Link>
      </header>

      {/* ── KPI strip ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
          <div className="p-3 bg-indigo-50 border border-indigo-100 rounded-xl">
            <Compass className="w-5 h-5 text-indigo-600" />
          </div>
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Active</p>
            <p className="text-2xl font-extrabold text-slate-800">{metrics.active}</p>
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
          <div className="p-3 bg-emerald-50 border border-emerald-100 rounded-xl">
            <FolderCheck className="w-5 h-5 text-emerald-600" />
          </div>
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Success Rate</p>
            <p className="text-2xl font-extrabold text-slate-800">{metrics.successRate}%</p>
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-xl p-4 shadow-sm flex items-center gap-4">
          <div className="p-3 bg-amber-50 border border-amber-100 rounded-xl">
            <DollarSign className="w-5 h-5 text-amber-600" />
          </div>
          <div>
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Total Cost</p>
            <p className="text-2xl font-extrabold text-amber-700">${metrics.totalCost.toFixed(2)}</p>
          </div>
        </div>
      </div>

      {/* ── Filters ── */}
      <div className="flex flex-col md:flex-row gap-3 items-center bg-slate-50 p-3 rounded-xl border border-slate-200">
        <div className="relative w-full md:w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search by domain or job ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="form-input pl-9"
          />
        </div>
        <div className="flex flex-wrap gap-2 w-full md:w-auto">
          {filterOptions.map((t) => (
            <button
              key={t.value}
              onClick={() => setStatusFilter(t.value)}
              className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold border transition-all ${
                statusFilter === t.value
                  ? "bg-indigo-600 text-white border-indigo-600 shadow-sm"
                  : "bg-white text-slate-600 border-slate-200 hover:border-slate-300"
              }`}
            >
              {t.label}
              {t.count > 0 && (
                <span className={`ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] font-bold ${
                  statusFilter === t.value ? "bg-white/20 text-white" : "bg-slate-100 text-slate-500"
                }`}>
                  {t.count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      {/* ── Table ── */}
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto overflow-y-auto max-h-[600px] custom-scrollbar">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left border-b border-slate-100 sticky top-0 z-10">
              <tr>
                <th className="px-6 py-3.5 font-semibold text-xs text-slate-500 uppercase tracking-wider">Job / Domain</th>
                <th className="px-6 py-3.5 font-semibold text-xs text-slate-500 uppercase tracking-wider">Created</th>
                <th className="px-6 py-3.5 font-semibold text-xs text-slate-500 uppercase tracking-wider text-center">URLs</th>
                <th className="px-6 py-3.5 font-semibold text-xs text-slate-500 uppercase tracking-wider text-center">Progress</th>
                <th className="px-6 py-3.5 font-semibold text-xs text-slate-500 uppercase tracking-wider text-center">Cost</th>
                <th className="px-6 py-3.5 font-semibold text-xs text-slate-500 uppercase tracking-wider text-center">Status</th>
                <th className="px-6 py-3.5 font-semibold text-xs text-slate-500 uppercase tracking-wider text-right"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading && [1, 2, 3, 4].map((i) => <SkeletonRow key={i} />)}

              {!isLoading && filteredJobs.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-6 py-16 text-center">
                    <div className="flex flex-col items-center gap-3 text-slate-400">
                      <FileStack className="w-10 h-10 opacity-30" />
                      <p className="text-sm font-medium">
                        {jobs?.length === 0 ? "No jobs yet — submit one from the dashboard." : "No jobs match your filter."}
                      </p>
                    </div>
                  </td>
                </tr>
              )}

              {filteredJobs.map((j: any) => (
                <tr key={j.id} className="hover:bg-slate-50/60 transition-colors">
                  <td className="px-6 py-4">
                    <Link href={`/jobs/${j.id}`}>
                      <JobLabel job={j} />
                    </Link>
                  </td>
                  <td className="px-6 py-4 text-slate-500 text-xs">
                    {new Date(j.created_at).toLocaleString(undefined, {
                      month: "short", day: "numeric",
                      hour: "numeric", minute: "2-digit",
                    })}
                  </td>
                  <td className="px-6 py-4 text-center font-semibold text-slate-700">{j.total_urls}</td>
                  <td className="px-6 py-4 text-center">
                    <span className="inline-flex items-center font-mono text-xs font-semibold bg-slate-100 text-slate-600 px-2 py-0.5 rounded-full border border-slate-200">
                      {j.completed}/{j.total_urls}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-center font-mono text-xs font-semibold text-slate-600">
                    ${(j.cost_usd ?? 0).toFixed(4)}
                  </td>
                  <td className="px-6 py-4 text-center">
                    <StatusBadge status={j.status} />
                  </td>
                  <td className="px-6 py-4 text-right">
                    <Link
                      href={`/jobs/${j.id}`}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 hover:border-indigo-300 bg-white text-xs font-semibold rounded-lg text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 transition-all"
                    >
                      View Details
                      <ArrowRight className="w-3 h-3" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!isLoading && jobs && jobs.length > 0 && (
          <div className="px-6 py-3 border-t border-slate-100 text-xs text-slate-400">
            Showing {filteredJobs.length} of {jobs.length} job{jobs.length !== 1 ? "s" : ""}
          </div>
        )}
      </div>
    </div>
  );
}
