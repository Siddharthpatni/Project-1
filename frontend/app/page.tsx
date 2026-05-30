"use client";

import useSWR from "swr";
import Link from "next/link";
import { fetcher, api } from "@/lib/api";
import JobSubmitForm from "@/components/JobSubmitForm";
import StatCard from "@/components/StatCard";
import {
  Activity,
  CheckCircle2,
  Cpu,
  DollarSign,
  TrendingUp,
  Layers,
  HelpCircle,
  ChevronRight,
  Zap,
} from "lucide-react";
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
} from "recharts";

const STRATEGIES_CONFIG = [
  { key: "manual_scraper",         label: "Manual",        color: "#3b82f6", desc: "Pre-written legacy scripts" },
  { key: "existing_scraper",       label: "Cached",        color: "#6366f1", desc: "Fast cached scrapers" },
  { key: "deterministic_template", label: "Deterministic", color: "#10b981", desc: "Direct ZIP URL construction" },
  { key: "llm_generated_scraper",  label: "LLM Generated", color: "#8b5cf6", desc: "Autonomous code synthesis" },
  { key: "computer_use_agent",     label: "CUA Fallback",  color: "#ec4899", desc: "Visual browser automation" },
  { key: "none",                   label: "Failure",       color: "#f43f5e", desc: "No strategy succeeded" },
];

const NAV_LINKS = [
  { label: "All Jobs",              href: "/jobs",       desc: "Monitor scraping tasks and outputs" },
  { label: "Scraper Registry",      href: "/scrapers",   desc: "View and manage auto-saved scrapers" },
  { label: "LLM Benchmarks",        href: "/evaluation", desc: "Compare model performance on datasets" },
  { label: "CUA Agent Runs",        href: "/agents",     desc: "Computer Use Agent session history" },
  { label: "System Health & Errors",href: "/admin",      desc: "Failed items, diagnostics & alerts" },
];

export default function HomePage() {
  const { data: stats, isLoading } = useSWR(api("/admin/stats"), fetcher, { refreshInterval: 5000 });

  const chartData = STRATEGIES_CONFIG.map((strat) => {
    const total     = stats?.strategy_distribution?.[strat.key] ?? 0;
    const succeeded = stats?.strategy_success_distribution?.[strat.key] ?? 0;
    const rate      = total > 0 ? Math.round((succeeded / total) * 100) : 0;
    return { ...strat, rate, total, succeeded };
  });

  const hasData = chartData.some((d) => d.total > 0);

  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">

      {/* ── Hero Banner ── */}
      <header className="relative rounded-2xl bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 p-8 text-white overflow-hidden shadow-xl border border-indigo-900/40">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(99,102,241,0.18),transparent_60%)] pointer-events-none" />
        <div className="relative z-10">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-500/15 border border-indigo-400/25 text-xs font-bold text-indigo-300 mb-4 tracking-wider uppercase">
            <Zap className="w-3.5 h-3.5 text-indigo-400 fill-indigo-400" />
            Agentic Cascade Scraper
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight">
            Vergabepilot<span className="text-indigo-400 font-black">.AI</span>
          </h1>
          <p className="text-slate-300 mt-3 text-sm sm:text-base leading-relaxed max-w-2xl">
            Automated public procurement document scraper. Enter any notice URL and the cascaded pipeline handles route discovery, autonomous agent execution, and validation.
          </p>
        </div>
      </header>

      {/* ── KPI Grid ── */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={<Activity className="w-5 h-5" />}
          label="Total Jobs"
          value={isLoading ? "—" : (stats?.jobs ?? 0)}
        />
        <StatCard
          icon={<CheckCircle2 className="w-5 h-5 text-emerald-500" />}
          label="Item Success Rate"
          value={isLoading ? "—" : `${Math.round((stats?.item_success_rate ?? 0) * 100)}%`}
        />
        <StatCard
          icon={<Cpu className="w-5 h-5" />}
          label="Scraper Templates"
          value={isLoading ? "—" : (stats?.scraper_templates ?? 0)}
        />
        <StatCard
          icon={<DollarSign className="w-5 h-5 text-amber-500" />}
          label="LLM Cost (USD)"
          value={isLoading ? "—" : `$${(stats?.total_cost_usd ?? 0).toFixed(2)}`}
          sub="Total spend across all jobs"
        />
      </section>

      {/* ── Main Layout ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">

        {/* Left column */}
        <div className="lg:col-span-2 space-y-8">

          {/* Submit form */}
          <section className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-sm">
            <div className="flex items-center gap-3 mb-6">
              <div className="p-2.5 bg-indigo-50 border border-indigo-100 rounded-xl">
                <Zap className="w-5 h-5 text-indigo-600" />
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-800">Submit New Scraping Job</h2>
                <p className="text-xs text-slate-500 mt-0.5">Provide one or more notice URLs to process through the cascade pipeline.</p>
              </div>
            </div>
            <JobSubmitForm />
          </section>

          {/* Strategy Success Rates chart */}
          <section className="bg-white border border-slate-200 rounded-2xl p-6 md:p-8 shadow-sm">
            <div className="flex items-center justify-between mb-1">
              <div className="flex items-center gap-2.5">
                <div className="p-2 bg-indigo-50 border border-indigo-100 rounded-xl">
                  <TrendingUp className="w-5 h-5 text-indigo-600" />
                </div>
                <h2 className="text-base font-bold text-slate-800">Strategy Success Rates</h2>
              </div>
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Live</span>
            </div>
            <p className="text-xs text-slate-500 mb-5 ml-[2.75rem]">
              Percentage of URLs successfully processed by each pipeline stage.
            </p>

            {!hasData ? (
              <div className="h-52 flex flex-col items-center justify-center text-slate-400 gap-2">
                <TrendingUp className="w-10 h-10 opacity-25" />
                <p className="text-sm font-medium">No data yet — submit your first job to see analytics.</p>
              </div>
            ) : (
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chartData} margin={{ top: 8, right: 8, left: -28, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                    <XAxis
                      dataKey="label"
                      tick={{ fill: "#94a3b8", fontSize: 10, fontWeight: 600 }}
                      axisLine={{ stroke: "#e2e8f0" }}
                      tickLine={false}
                    />
                    <YAxis
                      domain={[0, 100]}
                      tickFormatter={(v) => `${v}%`}
                      tick={{ fill: "#94a3b8", fontSize: 10, fontWeight: 600 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <Tooltip
                      cursor={{ fill: "#f8fafc", radius: 6 }}
                      content={({ active, payload }) => {
                        if (!active || !payload?.length) return null;
                        const d = payload[0].payload;
                        return (
                          <div className="bg-slate-900 text-white p-3.5 rounded-xl shadow-xl text-xs space-y-1.5 min-w-[190px]">
                            <p className="font-bold border-b border-slate-700 pb-1.5">{d.label}</p>
                            <p className="text-slate-400">{d.desc}</p>
                            <div className="flex justify-between font-mono font-bold pt-0.5">
                              <span>Success Rate</span>
                              <span className="text-emerald-400">{d.rate}%</span>
                            </div>
                            <div className="flex justify-between font-mono text-[10px] text-slate-400">
                              <span>Runs</span>
                              <span>{d.succeeded} / {d.total}</span>
                            </div>
                          </div>
                        );
                      }}
                    />
                    <Bar dataKey="rate" radius={[5, 5, 0, 0]} barSize={34}>
                      {chartData.map((entry, i) => (
                        <Cell key={i} fill={entry.color} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>
        </div>

        {/* Right column */}
        <div className="space-y-6">

          {/* Navigation cards */}
          <section className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-2.5 mb-4 pb-3 border-b border-slate-100">
              <Cpu className="w-5 h-5 text-indigo-600" />
              <h2 className="text-base font-bold text-slate-800">Pipeline Explorer</h2>
            </div>
            <ul className="space-y-2">
              {NAV_LINKS.map((link) => (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    className="flex items-center justify-between p-3 bg-slate-50 hover:bg-indigo-50 rounded-xl border border-slate-100 hover:border-indigo-200 transition-all group"
                  >
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-slate-700 group-hover:text-indigo-700 transition-colors">{link.label}</p>
                      <p className="text-[10px] text-slate-400 mt-0.5 truncate">{link.desc}</p>
                    </div>
                    <ChevronRight className="w-4 h-4 text-slate-400 group-hover:text-indigo-500 group-hover:translate-x-0.5 transition-all flex-shrink-0" />
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          {/* Volume breakdown */}
          <section className="bg-white border border-slate-200 rounded-2xl p-6 shadow-sm">
            <div className="flex items-center gap-2.5 mb-1 pb-3 border-b border-slate-100">
              <Layers className="w-4 h-4 text-indigo-600" />
              <h2 className="text-sm font-bold text-slate-800">Scraping Volume</h2>
            </div>
            <p className="text-[10px] text-slate-500 mb-3">Total processed notice URLs by strategy.</p>

            {!hasData ? (
              <p className="text-xs text-slate-400 py-4 text-center">No runs recorded yet.</p>
            ) : (
              <div className="space-y-2 max-h-72 overflow-y-auto custom-scrollbar pr-1">
                {chartData.map((strat) => (
                  <div
                    key={strat.key}
                    className="flex items-center justify-between p-2.5 bg-slate-50 rounded-lg border border-slate-100"
                  >
                    <div className="flex items-center gap-2.5 min-w-0">
                      <span
                        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                        style={{ backgroundColor: strat.color }}
                      />
                      <span className="text-xs font-medium text-slate-700 truncate">{strat.label}</span>
                    </div>
                    <span className="font-mono text-xs font-bold text-slate-600 flex-shrink-0">
                      {strat.total}
                    </span>
                  </div>
                ))}
              </div>
            )}

            <div className="pt-3 border-t border-slate-100 mt-3 text-[10px] text-slate-400 flex items-center gap-1.5">
              <HelpCircle className="w-3 h-3" />
              Auto-distributed based on portal layout.
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
