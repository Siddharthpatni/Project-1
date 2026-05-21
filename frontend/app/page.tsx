"use client";

import { useState } from "react";
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
  ShieldAlert,
  Zap,
  ArrowRight
} from "lucide-react";
import { 
  BarChart, 
  Bar, 
  Cell, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  ResponsiveContainer, 
  Tooltip 
} from "recharts";

const STRATEGIES_CONFIG = [
  { key: "existing_scraper", label: "Existing Scraper", color: "#6366f1", desc: "Fast cached scrapers" },
  { key: "deterministic_template", label: "Deterministic DTVP", color: "#10b981", desc: "Constructed zip downloads" },
  { key: "llm_generated_scraper", label: "LLM Generated Scraper", color: "#8b5cf6", desc: "Autonomous synthesis" },
  { key: "computer_use_agent", label: "CUA Fallback", color: "#ec4899", desc: "Visual browser automation" },
  { key: "manual_scraper", label: "Manual Scraper", color: "#3b82f6", desc: "Pre-written legacy scripts" },
  { key: "none", label: "Failure / None", color: "#f43f5e", desc: "No strategy succeeded" }
];

export default function HomePage() {
  const { data: stats } = useSWR(api("/admin/stats"), fetcher, { refreshInterval: 5000 });
  
  const chartData = STRATEGIES_CONFIG.map(strat => {
    const total = stats?.strategy_distribution?.[strat.key] ?? 0;
    const succeeded = stats?.strategy_success_distribution?.[strat.key] ?? 0;
    const rate = total > 0 ? Math.round((succeeded / total) * 100) : 0;
    
    return {
      strategy: strat.label,
      key: strat.key,
      rate,
      total,
      succeeded,
      color: strat.color,
      desc: strat.desc
    };
  });

  return (
    <div className="space-y-8 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
      {/* ── Sleek Gradient Banner ── */}
      <header className="relative rounded-3xl bg-gradient-to-br from-slate-950 via-indigo-950 to-slate-900 p-8 text-white overflow-hidden shadow-xl border border-indigo-900/40 flex flex-col md:flex-row md:items-center md:justify-between gap-6">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,rgba(99,102,241,0.2),transparent_60%)] animate-pulse" style={{ animationDuration: '6s' }} />
        <div className="relative z-10 max-w-3xl">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-400/20 text-xs font-bold text-indigo-300 mb-4 tracking-wider uppercase">
            <Zap className="w-3.5 h-3.5 text-indigo-400 fill-indigo-400" /> Agentic Cascade Scraper
          </div>
          <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight">
            Vergabepilot<span className="text-indigo-400 font-black">.AI</span>
          </h1>
          <p className="text-slate-350 mt-3 text-sm sm:text-base leading-relaxed font-medium">
            Automated public procurement scraper and pipeline supervisor. Enter any notice URL and our cascaded system handles route discovery, autonomous agent execution, and validation.
          </p>
        </div>
      </header>

      {/* ── KPI Grid ── */}
      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard 
          icon={<Activity className="w-5 h-5 text-indigo-650" />} 
          label="Total Jobs Submitted"      
          value={stats?.jobs ?? 0} 
        />
        <StatCard 
          icon={<CheckCircle2 className="w-5 h-5 text-emerald-500" />} 
          label="Item Success Rate"
          value={stats ? `${Math.round((stats.item_success_rate ?? 0) * 100)}%` : "0%"} 
        />
        <StatCard 
          icon={<Cpu className="w-5 h-5 text-indigo-500" />}      
          label="Active Scraper Templates" 
          value={stats?.scraper_templates ?? 0} 
        />
        <StatCard 
          icon={<DollarSign className="w-5 h-5 text-amber-500" />} 
          label="Total LLM Cost (USD)" 
          value={stats ? `$${(stats.total_cost_usd ?? 0).toFixed(4)}` : "$0.00"} 
        />
      </section>

      {/* ── Unified Operations & Performance Workspace ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        {/* Left Column: Primary Actions & Analytics */}
        <div className="lg:col-span-2 space-y-8">
          
          {/* Submit job form */}
          <div className="bg-white border border-slate-200/80 rounded-2xl p-6 md:p-8 bg-gradient-to-br from-indigo-50/10 via-white to-white space-y-5 shadow-sm hover:shadow transition-all duration-300">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-indigo-50 border border-indigo-150 rounded-xl text-indigo-600">
                <Zap className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-lg font-extrabold text-slate-800">Submit New Scraping Job</h2>
                <p className="text-xs text-slate-500 font-semibold mt-0.5">Provide one or more notice URLs to process through the cascade.</p>
              </div>
            </div>
            <JobSubmitForm />
          </div>

          {/* Success Rates (Vertical Chart) */}
          <div className="bg-white border border-slate-200/80 rounded-2xl p-6 md:p-8 flex flex-col justify-between shadow-sm hover:shadow transition-all duration-300">
            <div className="border-b border-slate-100 pb-3 mb-6">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2.5">
                  <div className="p-2 bg-indigo-50 border border-indigo-150 rounded-xl text-indigo-650">
                    <TrendingUp className="w-5 h-5" />
                  </div>
                  <h2 className="text-lg font-extrabold text-slate-800">Strategy Success Rates</h2>
                </div>
                <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Live Metrics</span>
              </div>
              <p className="text-xs text-slate-500 font-semibold">
                Percentage of notice URLs successfully processed by each pipeline strategy stage.
              </p>
            </div>

            <div className="h-[280px] w-full mt-2">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={chartData}
                  margin={{ top: 10, right: 10, left: -25, bottom: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                  <XAxis 
                    dataKey="strategy" 
                    tick={{ fill: "#94a3b8", fontSize: 9, fontWeight: 700 }}
                    axisLine={{ stroke: "#e2e8f0" }}
                    tickLine={false}
                  />
                  <YAxis 
                    domain={[0, 100]} 
                    tickFormatter={(val) => `${val}%`} 
                    tick={{ fill: "#94a3b8", fontSize: 10, fontWeight: 700 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip 
                    cursor={{ fill: "#f8fafc", radius: 6 }} 
                    content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        const data = payload[0].payload;
                        return (
                          <div className="bg-slate-950 text-white p-4 rounded-xl shadow-xl border-none text-xs space-y-2 max-w-[220px]">
                            <p className="font-extrabold border-b border-slate-800 pb-1.5">{data.strategy}</p>
                            <p className="text-slate-400 font-semibold">{data.desc}</p>
                            <div className="pt-1 flex justify-between font-mono font-bold">
                              <span>Success Rate:</span>
                              <span className="text-emerald-400">{data.rate}%</span>
                            </div>
                            <div className="flex justify-between font-mono text-[10px] text-slate-500 font-bold">
                              <span>Runs:</span>
                              <span>{data.succeeded} / {data.total}</span>
                            </div>
                          </div>
                        );
                      }
                      return null;
                    }}
                  />
                  <Bar dataKey="rate" radius={[5, 5, 0, 0]} isAnimationActive={true} barSize={36}>
                    {chartData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* Right Column: Navigation & Volumes */}
        <div className="space-y-8">
          
          {/* Quick links & navigation */}
          <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm hover:shadow transition-all duration-300">
            <div className="border-b border-slate-100 pb-3 mb-4">
              <h2 className="text-lg font-extrabold text-slate-800 flex items-center gap-2">
                <Cpu className="w-5 h-5 text-indigo-500" />
                Pipeline Explorer
              </h2>
            </div>
            <ul className="space-y-3">
              {[
                { label: "All Scraping Jobs", href: "/jobs", desc: "Monitor scraping tasks and outputs" },
                { label: "Scraper Registry (P3)", href: "/scrapers", desc: "View auto-saved scrapers" },
                { label: "LLM Benchmarks (P1)", href: "/evaluation", desc: "Compare benchmark datasets" },
                { label: "CUA Sandbox Runs (P2)", href: "/agents", desc: "Computer Use Agent sessions" },
                { label: "System Health & Errors", href: "/admin", desc: "Failed items & diagnostics" }
              ].map((link, idx) => (
                <li key={idx}>
                  <Link 
                    className="flex items-center justify-between p-3.5 bg-slate-50 hover:bg-indigo-50/20 rounded-xl border border-slate-100 hover:border-indigo-150 transition-all group active:scale-98" 
                    href={link.href}
                  >
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-slate-700 group-hover:text-indigo-650 transition-colors truncate">{link.label}</p>
                      <p className="text-[10px] text-slate-400 font-semibold truncate mt-0.5">{link.desc}</p>
                    </div>
                    <ChevronRight className="w-4 h-4 text-slate-450 group-hover:text-indigo-500 group-hover:translate-x-0.5 transition-all" />
                  </Link>
                </li>
              ))}
            </ul>
          </div>

          {/* Strategy volume and breakdown list */}
          <div className="bg-white border border-slate-200/80 rounded-2xl p-6 shadow-sm hover:shadow transition-all duration-300">
            <div className="border-b border-slate-100 pb-3 mb-4 flex items-center gap-2.5">
              <div className="p-1.5 bg-indigo-50 border border-indigo-100 rounded-lg text-indigo-600">
                <Layers className="w-4 h-4" />
              </div>
              <h2 className="text-md font-extrabold text-slate-800">Scraping Volume</h2>
            </div>
            <p className="text-xs text-slate-500 font-semibold mb-4">
              Breakdown of total processed notice URLs by strategy stage.
            </p>

            <div className="space-y-3 max-h-[310px] overflow-y-auto pr-1 custom-scrollbar">
              {chartData.map((strat) => (
                <div key={strat.key} className="flex items-center justify-between p-3 bg-slate-50 rounded-xl border border-slate-100 hover:border-slate-200 transition-all">
                  <div className="flex items-center gap-3 min-w-0">
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0 animate-pulse" style={{ backgroundColor: strat.color }} />
                    <div className="min-w-0">
                      <p className="text-xs font-bold text-slate-700 truncate">{strat.strategy}</p>
                      <p className="text-[10px] text-slate-400 font-semibold truncate mt-0.5">{strat.desc}</p>
                    </div>
                  </div>
                  <div className="text-right font-mono text-xs flex-shrink-0 font-bold">
                    <span className="text-slate-850">{strat.total}</span>
                    <span className="text-slate-400 text-[10px] ml-1">runs</span>
                  </div>
                </div>
              ))}
            </div>

            <div className="pt-4 border-t border-slate-100 mt-4 text-[10px] text-slate-400 font-semibold flex items-center gap-1.5 justify-center">
              <HelpCircle className="w-3.5 h-3.5" />
              Runs auto-distribute based on site layouts.
            </div>
          </div>
        </div>

      </div>
    </div>
  );
}
