"use client";

import useSWR from "swr";
import Link from "next/link";
import { fetcher, api } from "@/lib/api";
import JobSubmitForm from "@/components/JobSubmitForm";
import { KpiCard, SectionHeader, Empty, Skeleton } from "@/components/ui";
import {
  Activity, CheckCircle2, Cpu, DollarSign, TrendingUp,
  Layers, ChevronRight, Zap, FileText, Clock, AlertTriangle,
} from "lucide-react";
import {
  BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid,
  ResponsiveContainer, Tooltip,
} from "recharts";
import { strategyColors } from "@/lib/theme";
import type { AdminStats } from "@/lib/types";

const STRATEGIES = [
  { key: "manual_scraper",         label: "Manual",        desc: "Pre-written legacy scripts" },
  { key: "existing_scraper",       label: "Cached",        desc: "Fast cached scrapers" },
  { key: "deterministic_template", label: "Deterministic", desc: "Direct ZIP URL construction" },
  { key: "llm_generated_scraper",  label: "LLM Generated", desc: "Autonomous code synthesis" },
  { key: "computer_use_agent",     label: "CUA Fallback",  desc: "Visual browser automation" },
  { key: "none",                   label: "Failure",       desc: "No strategy succeeded" },
];

const NAV_LINKS = [
  { label: "All Jobs",           href: "/jobs",       icon: <Activity className="w-4 h-4" />,    desc: "Monitor scraping tasks and outputs" },
  { label: "Scraper Registry",   href: "/scrapers",   icon: <Cpu className="w-4 h-4" />,         desc: "View and manage auto-saved scrapers" },
  { label: "LLM Benchmarks",     href: "/evaluation", icon: <TrendingUp className="w-4 h-4" />,  desc: "Compare model performance on datasets" },
  { label: "CUA Agent Runs",     href: "/agents",     icon: <Zap className="w-4 h-4" />,         desc: "Computer Use Agent session history" },
  { label: "System Health",      href: "/admin",      icon: <AlertTriangle className="w-4 h-4" />, desc: "Failed items, diagnostics & alerts" },
];

interface ChartPayloadEntry {
  payload: { label: string; desc: string; rate: number; succeeded: number; total: number };
}

function ChartTooltipContent({ active, payload }: { active?: boolean; payload?: ChartPayloadEntry[] }) {
  if (!active || !payload?.length) return null;
  const d = payload[0].payload;
  return (
    <div className="rounded-xl p-3.5 shadow-xl text-xs space-y-2 min-w-[190px]"
         style={{ background: "var(--fg)", color: "var(--bg-elevated)" }}>
      <p className="font-bold pb-1.5" style={{ borderBottom: "1px solid rgba(255,255,255,0.15)" }}>{d.label}</p>
      <p style={{ opacity: 0.7 }}>{d.desc}</p>
      <div className="flex justify-between font-mono font-bold pt-0.5">
        <span>Success Rate</span>
        <span style={{ color: "#34d399" }}>{d.rate}%</span>
      </div>
      <div className="flex justify-between font-mono text-[10px]" style={{ opacity: 0.6 }}>
        <span>Runs</span>
        <span>{d.succeeded} / {d.total}</span>
      </div>
    </div>
  );
}

export default function HomePage() {
  const { data: stats, isLoading } = useSWR<AdminStats>(
    api("/admin/stats"),
    fetcher,
    {
      // Only poll when there are active jobs; otherwise refresh every 30s
      refreshInterval: (data: AdminStats | undefined) =>
        (data?.items ?? 0) > 0 && (data?.pending ?? 0) + ((data as any)?.running ?? 0) > 0
          ? 5000
          : 30_000,
    }
  );

  const chartData = STRATEGIES.map((s) => {
    const total     = stats?.strategy_distribution?.[s.key] ?? 0;
    const succeeded = stats?.strategy_success_distribution?.[s.key] ?? 0;
    const rate      = total > 0 ? Math.round((succeeded / total) * 100) : 0;
    return { ...s, rate, total, succeeded, color: strategyColors[s.key] ?? "#94a3b8" };
  });

  const hasData = chartData.some((d) => d.total > 0);

  return (
    <div className="space-y-8 animate-fade-up">

      {/* Hero */}
      <header className="relative rounded-2xl overflow-hidden"
              style={{ background: "linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%)" }}>
        <div className="absolute inset-0 pointer-events-none"
             style={{ background: "radial-gradient(ellipse at 70% 0%, rgba(99,102,241,0.25) 0%, transparent 60%)" }} />
        <div className="relative z-10 px-8 py-10 text-white">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-bold tracking-wider uppercase mb-5"
               style={{ background: "rgba(99,102,241,0.2)", border: "1px solid rgba(99,102,241,0.35)", color: "#a5b4fc" }}>
            <Zap className="w-3.5 h-3.5 fill-current" />
            Agentic Cascade Scraper
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight">
            Vergabepilot<span style={{ color: "#818cf8" }}>.AI</span>
          </h1>
          <p className="mt-2 text-sm sm:text-base leading-relaxed max-w-xl" style={{ color: "#94a3b8" }}>
            Automated public procurement document scraper. Enter any notice URL and the cascaded pipeline handles route discovery, autonomous agent execution, and document extraction.
          </p>
        </div>
      </header>

      {/* KPI Grid */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard
          label="Total Jobs"
          value={stats?.jobs ?? 0}
          icon={<Activity className="w-5 h-5" />}
          loading={isLoading}
          color="brand"
        />
        <KpiCard
          label="Success Rate"
          value={`${Math.round((stats?.item_success_rate ?? 0) * 100)}%`}
          icon={<CheckCircle2 className="w-5 h-5" />}
          loading={isLoading}
          color="success"
          sub="Per URL item"
        />
        <KpiCard
          label="Scraper Templates"
          value={stats?.scraper_templates ?? 0}
          icon={<Cpu className="w-5 h-5" />}
          loading={isLoading}
        />
        <KpiCard
          label="LLM Cost (USD)"
          value={`$${(stats?.total_cost_usd ?? 0).toFixed(3)}`}
          icon={<DollarSign className="w-5 h-5" />}
          loading={isLoading}
          color="warning"
          sub="All-time total"
        />
      </section>

      {/* Main layout */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Left column */}
        <div className="lg:col-span-2 space-y-6">

          {/* Submit form */}
          <div className="card p-6">
            <div className="flex items-center gap-3 mb-5"
                 style={{ borderBottom: "1px solid var(--border)", paddingBottom: "1rem" }}>
              <div className="p-2.5 rounded-xl" style={{ background: "var(--brand-light)", color: "var(--brand)" }}>
                <Zap className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-subheading">Submit Scraping Job</h2>
                <p className="text-xs mt-0.5" style={{ color: "var(--fg-subtle)" }}>
                  Paste one or more notice URLs — the cascade pipeline handles the rest.
                </p>
              </div>
            </div>
            <JobSubmitForm />
          </div>

          {/* Strategy chart */}
          <div className="card p-6">
            <div className="flex items-center justify-between mb-1"
                 style={{ borderBottom: "1px solid var(--border)", paddingBottom: "0.875rem", marginBottom: "1.25rem" }}>
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-xl" style={{ background: "var(--brand-light)", color: "var(--brand)" }}>
                  <TrendingUp className="w-4 h-4" />
                </div>
                <div>
                  <h2 className="text-subheading">Strategy Success Rates</h2>
                  <p className="text-xs mt-0.5" style={{ color: "var(--fg-subtle)" }}>
                    % of URLs successfully processed by each pipeline stage
                  </p>
                </div>
              </div>
              <span className="text-xs font-bold px-2.5 py-1 rounded-full"
                    style={{ background: "var(--bg-subtle)", color: "var(--fg-subtle)" }}>
                Live
              </span>
            </div>

            {isLoading ? (
              <div className="h-56 flex items-end gap-4 px-4 pb-4">
                {[60, 80, 45, 70, 35, 50].map((h, i) => (
                  <div key={i} className="flex-1 skeleton rounded-t-md" style={{ height: `${h}%` }} />
                ))}
              </div>
            ) : !hasData ? (
              <Empty
                icon={<TrendingUp className="w-12 h-12" />}
                title="No data yet"
                description="Submit your first job to see strategy analytics."
                className="h-48"
              />
            ) : (
              <div className="h-60 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 4, left: -28, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false}
                                   stroke="var(--border)" strokeOpacity={0.6} />
                    <XAxis dataKey="label"
                           tick={{ fill: "var(--fg-subtle)", fontSize: 10, fontWeight: 600 }}
                           axisLine={{ stroke: "var(--border)" }} tickLine={false} />
                    <YAxis domain={[0, 100]} tickFormatter={(v) => `${v}%`}
                           tick={{ fill: "var(--fg-subtle)", fontSize: 10, fontWeight: 600 }}
                           axisLine={false} tickLine={false} />
                    <Tooltip cursor={{ fill: "var(--bg-subtle)", radius: 6 }}
                             content={<ChartTooltipContent />} />
                    <Bar dataKey="rate" radius={[6, 6, 0, 0]} barSize={32}>
                      {chartData.map((entry, i) => (
                        <Cell key={i} fill={entry.color} opacity={0.9} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-5">

          {/* Quick links */}
          <div className="card p-5">
            <h2 className="text-subheading mb-4 pb-3" style={{ borderBottom: "1px solid var(--border)" }}>
              Pipeline Explorer
            </h2>
            <ul className="space-y-1.5">
              {NAV_LINKS.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="nav-link flex items-center gap-3 p-3 rounded-xl transition-all group"
                  >
                    <span style={{ color: "var(--brand)", opacity: 0.8 }}>{link.icon}</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-semibold" style={{ color: "var(--fg)" }}>{link.label}</p>
                      <p className="text-[10px] truncate" style={{ color: "var(--fg-subtle)" }}>{link.desc}</p>
                    </div>
                    <ChevronRight className="w-3.5 h-3.5 flex-shrink-0 transition-transform group-hover:translate-x-0.5"
                                  style={{ color: "var(--fg-subtle)" }} />
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Volume breakdown */}
          <div className="card p-5">
            <h2 className="text-subheading mb-1 pb-3" style={{ borderBottom: "1px solid var(--border)", marginBottom: "0.75rem" }}>
              Scraping Volume
            </h2>

            {isLoading ? (
              <div className="space-y-2">
                {[1,2,3,4].map((i) => <Skeleton key={i} height="2.5rem" className="rounded-xl" />)}
              </div>
            ) : !hasData ? (
              <p className="text-xs py-6 text-center" style={{ color: "var(--fg-subtle)" }}>No runs recorded yet.</p>
            ) : (
              <div className="space-y-1.5">
                {chartData.filter(s => s.total > 0).map((strat) => (
                  <div key={strat.key} className="flex items-center gap-2.5 px-3 py-2 rounded-lg"
                       style={{ background: "var(--bg-subtle)" }}>
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                          style={{ background: strat.color }} />
                    <span className="text-xs font-medium flex-1 truncate" style={{ color: "var(--fg)" }}>
                      {strat.label}
                    </span>
                    <span className="font-mono text-xs font-bold" style={{ color: "var(--fg-muted)" }}>
                      {strat.total}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <p className="text-[10px] mt-3 pt-3 flex items-center gap-1"
               style={{ color: "var(--fg-subtle)", borderTop: "1px solid var(--border)" }}>
              Auto-distributed based on portal type.
            </p>
          </div>

          {/* Recent activity */}
          <RecentJobs />
        </div>
      </div>
    </div>
  );
}

function RecentJobs() {
  const { data: jobs, isLoading } = useSWR(api("/jobs?limit=5"), fetcher, { refreshInterval: 8000 });

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4 pb-3"
           style={{ borderBottom: "1px solid var(--border)" }}>
        <h2 className="text-subheading">Recent Jobs</h2>
        <Link href="/jobs" className="text-xs font-semibold flex items-center gap-1"
              style={{ color: "var(--brand)" }}>
          View all <ChevronRight className="w-3 h-3" />
        </Link>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[1,2,3].map((i) => <Skeleton key={i} height="3rem" className="rounded-lg" />)}
        </div>
      ) : !jobs?.length ? (
        <p className="text-xs py-4 text-center" style={{ color: "var(--fg-subtle)" }}>No jobs yet.</p>
      ) : (
        <div className="space-y-1.5">
          {jobs.slice(0, 5).map((job: any) => (
            <Link key={job.id} href={`/jobs/${job.id}`}
                  className="recent-job-link flex items-center gap-2.5 p-2.5 rounded-lg transition-all"
                  >
              <div className={`w-2 h-2 rounded-full flex-shrink-0 ${
                job.status === "success" ? "bg-emerald-500" :
                job.status === "failed" ? "bg-rose-500" :
                job.status === "running" ? "bg-amber-400 animate-pulse" : "bg-slate-400"
              }`} />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-mono font-semibold truncate" style={{ color: "var(--fg)" }}>
                  {(job.domains?.[0] ?? job.id.slice(0, 12)) + (job.domains?.length > 1 ? ` +${job.domains.length - 1}` : "")}
                </p>
                <p className="text-[10px]" style={{ color: "var(--fg-subtle)" }}>
                  {job.completed}/{job.total_urls} URLs
                </p>
              </div>
              <span className="text-[10px] font-mono flex-shrink-0" style={{ color: "var(--fg-subtle)" }}>
                {new Date(job.created_at).toLocaleDateString()}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
