"use client";

import useSWR from "swr";
import { useState, useMemo } from "react";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import { Activity, ArrowLeft, Search, Filter, FolderCheck, Compass, DollarSign, ArrowRight } from "lucide-react";

function JobLabel({ job }: { job: any }) {
  return (
    <div className="flex flex-col gap-1 w-full">
      {job.domains?.length > 0 ? (
        <div>
          <div className="font-semibold text-slate-800 truncate max-w-[32ch] hover:text-indigo-650" title={job.domains.join(", ")}>
            {job.domains.slice(0, 2).join(", ")}{job.domains.length > 2 ? ` +${job.domains.length - 2}` : ""}
          </div>
          <div className="text-[10px] font-bold font-mono text-slate-400 mt-0.5">{job.id.slice(0, 8)}…</div>
        </div>
      ) : (
        <span className="font-mono text-xs font-bold text-slate-700">{job.id.slice(0, 8)}…</span>
      )}
      
      {(job.status === "pending" || job.status === "running") && job.total_urls > 0 && (
        <div className="w-full max-w-[140px] bg-slate-100 rounded-full h-1 mt-1.5 overflow-hidden">
          <div 
            className="bg-indigo-600 h-1 rounded-full transition-all duration-300"
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

  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");

  const metrics = useMemo(() => {
    if (!jobs || jobs.length === 0) return { active: 0, successRate: 0, docsCount: 0, totalCost: 0 };
    let active = 0;
    let completedCount = 0;
    let successfulCount = 0;
    let totalCost = 0;
    
    for (const j of jobs) {
      if (j.status === "pending" || j.status === "running") {
        active++;
      } else {
        completedCount++;
        if (j.status === "success" || j.status === "completed") {
          successfulCount++;
        }
      }
      totalCost += j.cost_usd ?? 0;
    }

    const successRate = completedCount ? Math.round((successfulCount / completedCount) * 100) : 100;
    return { active, successRate, totalCost };
  }, [jobs]);

  const filteredJobs = useMemo(() => {
    if (!jobs) return [];
    return jobs.filter((j: any) => {
      const matchSearch = (j.domains || []).some((d: string) => d.toLowerCase().includes(search.toLowerCase())) || j.id.toLowerCase().includes(search.toLowerCase());
      if (statusFilter === "all") return matchSearch;
      if (statusFilter === "active") return (j.status === "pending" || j.status === "running") && matchSearch;
      if (statusFilter === "completed") return (j.status === "success" || j.status === "completed") && matchSearch;
      if (statusFilter === "failed") return j.status === "failed" && matchSearch;
      return matchSearch;
    });
  }, [jobs, search, statusFilter]);

  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-100 pb-5">
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight flex items-center gap-3">
            <Activity className="w-8 h-8 text-indigo-600 animate-pulse" />
            Task Manager
          </h1>
          <p className="text-slate-500 mt-1.5 text-sm sm:text-base font-medium">
            Monitor and audit active document retrieval jobs and cascading pipeline executions.
          </p>
        </div>
      </header>

      {/* ── Stats Summary Grid ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
        <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm flex items-center gap-4">
          <div className="p-3.5 bg-indigo-50 border border-indigo-100 rounded-xl">
            <Compass className="w-6 h-6 text-indigo-650 animate-spin" style={{ animationDuration: '8s' }} />
          </div>
          <div>
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Active Workers</div>
            <div className="text-2xl font-extrabold text-slate-800 mt-1">{metrics.active} tasks</div>
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm flex items-center gap-4">
          <div className="p-3.5 bg-emerald-50 border border-emerald-100 rounded-xl">
            <FolderCheck className="w-6 h-6 text-emerald-600" />
          </div>
          <div>
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Job Success Rate</div>
            <div className="text-2xl font-extrabold text-slate-800 mt-1">{metrics.successRate}%</div>
          </div>
        </div>
        <div className="bg-white border border-slate-200 rounded-2xl p-5 shadow-sm flex items-center gap-4">
          <div className="p-3.5 bg-amber-50 border border-amber-100 rounded-xl">
            <DollarSign className="w-6 h-6 text-amber-600" />
          </div>
          <div>
            <div className="text-xs font-bold text-slate-400 uppercase tracking-wider">Processing Cost</div>
            <div className="text-2xl font-extrabold text-amber-700 mt-1">${metrics.totalCost.toFixed(4)}</div>
          </div>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col md:flex-row gap-4 justify-between items-center bg-slate-50 p-4 rounded-2xl border border-slate-200/80">
        <div className="relative w-full md:w-80">
          <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search by ID or domain..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-10 pr-4 py-2 border border-slate-250 rounded-xl text-sm focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-all shadow-inner bg-white font-medium"
          />
        </div>

        <div className="flex flex-wrap gap-2 w-full md:w-auto">
          {[
            { value: "all", label: "All Jobs" },
            { value: "active", label: "Active" },
            { value: "completed", label: "Completed" },
            { value: "failed", label: "Failed" },
          ].map((t) => (
            <button
              key={t.value}
              onClick={() => setStatusFilter(t.value)}
              className={`px-4 py-2 rounded-xl text-xs font-bold border transition-all active:scale-95 cursor-pointer ${
                statusFilter === t.value
                  ? "bg-indigo-600 text-white border-indigo-600 shadow-sm"
                  : "bg-white text-slate-650 border-slate-200 hover:border-slate-300"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Jobs Table ── */}
      <div className="bg-white border border-slate-200/80 rounded-2xl shadow-sm overflow-hidden">
        <div className="overflow-x-auto overflow-y-auto max-h-[600px] custom-scrollbar">
          <table className="w-full text-sm">
            <thead className="bg-slate-50/95 backdrop-blur-sm text-left text-slate-500 border-b border-slate-100 sticky top-0 z-10 shadow-sm">
              <tr>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider">Job / Target Domain</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider">Created At</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">URLs</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Progress</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Cost</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-center">Status</th>
                <th className="px-6 py-4 font-bold text-xs uppercase tracking-wider text-right">Details</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {isLoading && (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-slate-400 font-semibold">
                    Fetching tasks…
                  </td>
                </tr>
              )}
              {!isLoading && filteredJobs.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-slate-400 font-semibold">
                    No matching jobs found in record history.
                  </td>
                </tr>
              )}
              {filteredJobs.map((j: any) => (
                <tr key={j.id} className="hover:bg-slate-50/30 transition-colors">
                  <td className="px-6 py-4">
                    <Link href={`/jobs/${j.id}`} className="block">
                      <JobLabel job={j} />
                    </Link>
                  </td>
                  <td className="px-6 py-4 text-slate-500 font-medium">
                    {new Date(j.created_at).toLocaleString(undefined, {
                      month: 'short',
                      day: 'numeric',
                      hour: 'numeric',
                      minute: '2-digit'
                    })}
                  </td>
                  <td className="px-6 py-4 text-center font-bold text-slate-700">{j.total_urls}</td>
                  <td className="px-6 py-4 text-center">
                    <span className="inline-flex items-center justify-center font-mono text-xs font-bold bg-slate-100 text-slate-700 px-2.5 py-1 rounded-full border border-slate-200">
                      {j.completed}/{j.total_urls}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-center font-bold text-slate-600">${(j.cost_usd ?? 0).toFixed(4)}</td>
                  <td className="px-6 py-4 text-center">
                    <div className="inline-flex justify-center">
                      <StatusBadge status={j.status} />
                    </div>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <Link 
                      href={`/jobs/${j.id}`}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 border border-slate-200 hover:border-slate-350 bg-white text-xs font-bold rounded-lg text-indigo-650 hover:text-indigo-700 hover:shadow-sm transition-all active:scale-95 cursor-pointer"
                    >
                      Audit
                      <ArrowRight className="w-3 h-3" />
                    </Link>
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
