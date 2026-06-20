/**
 * Jobs list page — paginated table of all submitted scraping jobs.
 *
 * Each row shows the job's status, number of URLs processed, success count,
 * LLM cost, and the first domain (+ overflow count). Clicking a row navigates
 * to the job detail page for per-URL breakdown and document downloads.
 *
 * Features:
 *   - Status filter chips (All / Running / Success / Partial / Failed)
 *   - Live updates: auto-refreshes every 5s when any job is running
 *   - Delete job with confirmation prompt
 *
 * Data source: GET /api/jobs?limit=50 (newest first)
 */
"use client";

import useSWR from "swr";
import { useState, useMemo } from "react";
import Link from "next/link";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import { SearchInput, KpiCard, Empty, Skeleton, Tabs, SectionHeader } from "@/components/ui";
import { Activity, FolderCheck, DollarSign, Compass, ArrowRight, FileStack, Zap } from "lucide-react";
import type { Job } from "@/lib/types";
import { useDebounce } from "@/lib/hooks";

function SkeletonRow() {
  return (
    <tr>
      {[1, 2, 3, 4, 5, 6, 7].map((i) => (
        <td key={i} className="px-4 py-4">
          <Skeleton height="1rem" width={i === 1 ? "80%" : i === 7 ? "60%" : "70%"} />
        </td>
      ))}
    </tr>
  );
}

function ProgressPill({ completed, total }: { completed: number; total: number }) {
  const pct = total > 0 ? Math.round((completed / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 rounded-full h-1.5 overflow-hidden" style={{ background: "var(--bg-muted)" }}>
        <div
          className="h-1.5 rounded-full transition-all duration-500"
          style={{ width: `${Math.max(4, pct)}%`, background: pct === 100 ? "#10b981" : "var(--brand)" }}
        />
      </div>
      <span className="text-[10px] font-mono" style={{ color: "var(--fg-subtle)" }}>
        {completed}/{total}
      </span>
    </div>
  );
}

/** Mobile row — a tappable card shown instead of the table on small screens. */
function JobCard({ job }: { job: Job }) {
  const domains = job.domains ?? [];
  const active = job.status === "pending" || job.status === "running";
  return (
    <Link
      href={`/jobs/${job.id}`}
      className="card card-hover block p-4 active:scale-[0.99] transition-transform"
      aria-label={`Open job ${domains[0] ?? job.id.slice(0, 8)}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-semibold text-sm truncate" style={{ color: "var(--fg)" }} title={domains.join(", ")}>
            {domains.length ? domains.slice(0, 2).join(", ") : `${job.id.slice(0, 12)}…`}
            {domains.length > 2 && <span style={{ color: "var(--fg-subtle)" }}> +{domains.length - 2}</span>}
          </p>
          <p className="font-mono text-[10px] mt-0.5" style={{ color: "var(--fg-subtle)" }}>{job.id.slice(0, 8)}…</p>
        </div>
        <StatusBadge status={job.status} />
      </div>
      <div className="mt-3 flex items-center justify-between gap-3">
        {active
          ? <ProgressPill completed={job.completed} total={job.total_urls} />
          : <span className="font-mono text-xs" style={{ color: "var(--fg-subtle)" }}>{job.completed}/{job.total_urls} URLs</span>}
        <span className="font-mono text-xs" style={{ color: "var(--fg-muted)" }}>${(job.cost_usd ?? 0).toFixed(4)}</span>
      </div>
    </Link>
  );
}

const FILTER_TABS = [
  { id: "all",       label: "All" },
  { id: "active",    label: "Active" },
  { id: "completed", label: "Done" },
  { id: "failed",    label: "Failed" },
];

export default function JobsPage() {
  const { data: jobs, isLoading } = useSWR<Job[]>(api("/jobs"), fetcher, {
    refreshInterval: (data) =>
      data?.some((j) => j.status === "pending" || j.status === "running") ? 3000 : 0,
  });

  const [rawSearch, setRawSearch]    = useState("");
  const [statusFilter, setStatus]    = useState("all");
  const search = useDebounce(rawSearch, 250);

  const metrics = useMemo(() => {
    if (!jobs?.length) return { active: 0, successRate: 0, totalCost: 0, total: 0 };
    let active = 0, completed = 0, successful = 0, totalCost = 0;
    for (const j of jobs) {
      if (j.status === "pending" || j.status === "running") active++;
      else { completed++; if (j.status === "success") successful++; }
      totalCost += j.cost_usd ?? 0;
    }
    return { active, successRate: completed ? Math.round((successful / completed) * 100) : 0, totalCost, total: jobs.length };
  }, [jobs]);

  const filtered = useMemo(() => {
    if (!jobs) return [];
    return jobs.filter((j) => {
      const q = search.toLowerCase();
      const matchSearch = !q ||
        (j.domains ?? []).some((d) => d.toLowerCase().includes(q)) ||
        j.id.toLowerCase().includes(q);
      if (!matchSearch) return false;
      if (statusFilter === "active")    return j.status === "pending" || j.status === "running";
      if (statusFilter === "completed") return j.status === "success" || j.status === "partial";
      if (statusFilter === "failed")    return j.status === "failed";
      return true;
    });
  }, [jobs, search, statusFilter]);

  const tabsWithCounts = FILTER_TABS.map((t) => ({
    ...t,
    count: t.id === "all"       ? (jobs?.length ?? 0) :
           t.id === "active"    ? metrics.active :
           t.id === "completed" ? (jobs?.filter(j => j.status === "success" || j.status === "partial").length ?? 0) :
                                  (jobs?.filter(j => j.status === "failed").length ?? 0),
  }));

  return (
    <div className="space-y-6 animate-fade-up">

      <SectionHeader
        title="Jobs"
        description="Monitor active and historical document retrieval jobs."
        icon={<Activity className="w-5 h-5" />}
        action={
          <Link href="/" className="btn btn-primary btn-sm">
            <Zap className="w-3.5 h-3.5" /> New Job
          </Link>
        }
      />

      {/* KPI strip */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <KpiCard label="Total Jobs"    value={metrics.total}                     icon={<FileStack className="w-4 h-4" />}   loading={isLoading} color="brand" />
        <KpiCard label="Active"        value={metrics.active}                    icon={<Compass className="w-4 h-4" />}    loading={isLoading} color={metrics.active > 0 ? "warning" : "default"} />
        <KpiCard label="Success Rate"  value={`${metrics.successRate}%`}         icon={<FolderCheck className="w-4 h-4" />} loading={isLoading} color="success" />
        <KpiCard label="LLM Cost"      value={`$${metrics.totalCost.toFixed(3)}`} icon={<DollarSign className="w-4 h-4" />} loading={isLoading} color="warning" />
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        <SearchInput
          value={rawSearch}
          onChange={setRawSearch}
          placeholder="Search domain or job ID…"
          className="w-full sm:w-72"
        />
        <Tabs tabs={tabsWithCounts} active={statusFilter} onChange={setStatus} />
        <span className="text-xs ml-auto hidden sm:block" style={{ color: "var(--fg-subtle)" }}>
          {filtered.length} job{filtered.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Mobile: stacked cards (no horizontal scrolling on phones) */}
      <div className="md:hidden space-y-3">
        {isLoading && Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="card p-4"><Skeleton height="3.25rem" /></div>
        ))}
        {!isLoading && filtered.length === 0 && (
          <Empty
            icon={<FileStack className="w-10 h-10" />}
            title={search ? "No jobs match your search" : "No jobs yet"}
            description={search ? "Try a different search term." : "Submit a URL on the dashboard to start scraping."}
            action={!search && (
              <Link href="/" className="btn btn-primary btn-sm"><Zap className="w-3.5 h-3.5" /> Submit Job</Link>
            )}
          />
        )}
        {!isLoading && filtered.map((job) => <JobCard key={job.id} job={job} />)}
      </div>

      {/* Desktop: table */}
      <div className="card overflow-hidden hidden md:block">
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Job / Domains</th>
                <th>Status</th>
                <th>Progress</th>
                <th className="hidden md:table-cell">Cost</th>
                <th className="hidden lg:table-cell">Created</th>
                <th className="text-right">Action</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)}

              {!isLoading && filtered.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <Empty
                      icon={<FileStack className="w-10 h-10" />}
                      title={search ? "No jobs match your search" : "No jobs yet"}
                      description={search ? "Try a different search term." : "Submit a URL on the dashboard to start scraping."}
                      action={
                        !search && (
                          <Link href="/" className="btn btn-primary btn-sm">
                            <Zap className="w-3.5 h-3.5" /> Submit Job
                          </Link>
                        )
                      }
                    />
                  </td>
                </tr>
              )}

              {filtered.map((job) => (
                <tr key={job.id} className="group">
                  <td className="max-w-0">
                    <div>
                      {(job.domains ?? []).length > 0 ? (
                        <>
                          <p className="font-semibold text-sm truncate max-w-[28ch]"
                             style={{ color: "var(--fg)" }}
                             title={(job.domains ?? []).join(", ")}>
                            {(job.domains ?? []).slice(0, 2).join(", ")}
                            {(job.domains ?? []).length > 2 && (
                              <span style={{ color: "var(--fg-subtle)" }}> +{(job.domains ?? []).length - 2}</span>
                            )}
                          </p>
                          <p className="font-mono text-[10px] mt-0.5" style={{ color: "var(--fg-subtle)" }}>
                            {job.id.slice(0, 8)}…
                          </p>
                        </>
                      ) : (
                        <p className="font-mono text-xs font-semibold" style={{ color: "var(--fg)" }}>
                          {job.id.slice(0, 12)}…
                        </p>
                      )}
                    </div>
                  </td>
                  <td><StatusBadge status={job.status} /></td>
                  <td>
                    {(job.status === "pending" || job.status === "running") ? (
                      <ProgressPill completed={job.completed} total={job.total_urls} />
                    ) : (
                      <span className="font-mono text-xs" style={{ color: "var(--fg-subtle)" }}>
                        {job.completed}/{job.total_urls}
                      </span>
                    )}
                  </td>
                  <td className="hidden md:table-cell font-mono text-xs" style={{ color: "var(--fg-muted)" }}>
                    ${(job.cost_usd ?? 0).toFixed(4)}
                  </td>
                  <td className="hidden lg:table-cell text-xs" style={{ color: "var(--fg-subtle)" }}>
                    {new Date(job.created_at).toLocaleString(undefined, {
                      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"
                    })}
                  </td>
                  <td className="text-right">
                    <Link
                      href={`/jobs/${job.id}`}
                      className="btn btn-secondary btn-xs"
                    >
                      View <ArrowRight className="w-3 h-3" />
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
