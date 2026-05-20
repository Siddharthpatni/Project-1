"use client";

import useSWR from "swr";
import Link from "next/link";
import { fetcher, api } from "@/lib/api";
import JobSubmitForm from "@/components/JobSubmitForm";
import StatCard from "@/components/StatCard";
import { Activity, CheckCircle2, Cpu, DollarSign } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from "recharts";

export default function HomePage() {
  const { data: stats } = useSWR(api("/admin/stats"), fetcher, { refreshInterval: 5000 });

  return (
    <div className="space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
            Vergabepilot<span className="text-brand-600">.AI</span>
          </h1>
          <p className="text-slate-600 mt-2 text-sm max-w-2xl">
            Input procurement URLs and let the cascaded pipeline (Existing Scraper → LLM-generated → CUA Fallback) handle the rest.
          </p>
        </div>
      </header>

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={<Activity className="w-5 h-5" />} label="Jobs"      value={stats?.jobs ?? "—"} />
        <StatCard icon={<CheckCircle2 className="w-5 h-5" />} label="Item success rate"
                  value={stats ? `${Math.round((stats.item_success_rate ?? 0) * 100)}%` : "—"} />
        <StatCard icon={<Cpu className="w-5 h-5" />}      label="Scraper templates" value={stats?.scraper_templates ?? "—"} />
        <StatCard icon={<DollarSign className="w-5 h-5" />} label="LLM spend (USD)" value={stats ? `$${(stats.total_cost_usd ?? 0).toFixed(2)}` : "—"} />
      </section>

      {stats && stats.strategy_distribution && Object.keys(stats.strategy_distribution).length > 0 && (
        <section className="card p-6 border-2 border-slate-100">
          <div className="flex items-center gap-2 mb-4">
            <Activity className="w-5 h-5 text-brand-600" />
            <h2 className="text-lg font-semibold text-slate-800">Strategy Success Rates</h2>
          </div>
          <div className="h-[240px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                layout="vertical"
                data={Object.keys(stats.strategy_distribution).filter(k => stats.strategy_distribution[k] > 0).map(k => ({
                  strategy: k.replace(/_/g, " "),
                  rate: Math.round(((stats.strategy_success_distribution?.[k] || 0) / stats.strategy_distribution[k]) * 100)
                }))}
                margin={{ top: 0, right: 30, left: 60, bottom: 0 }}
              >
                <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#e2e8f0" />
                <XAxis type="number" domain={[0, 100]} tickFormatter={(val) => `${val}%`} tick={{ fill: "#475569", fontSize: 12 }} />
                <YAxis dataKey="strategy" type="category" tick={{ fill: "#475569", fontSize: 12 }} width={140} />
                <Tooltip cursor={{ fill: "#f1f5f9" }} formatter={(val) => [`${val}%`, "Success Rate"]} />
                <Bar dataKey="rate" fill="#0ea5e9" radius={[0, 4, 4, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="card p-6 lg:col-span-2 border-2 border-dashed border-brand-200 bg-gradient-to-br from-brand-50/30 to-white">
          <div className="flex items-center gap-2 mb-4">
            <div className="p-2 bg-brand-100 rounded-lg">
              <Activity className="w-5 h-5 text-brand-600" />
            </div>
            <h2 className="text-lg font-semibold text-brand-950">Submit New Scraping Job</h2>
          </div>
          <JobSubmitForm />
        </div>

        <div className="card p-6 bg-slate-50 border-slate-200">
          <h2 className="text-lg font-semibold mb-4 text-slate-800">Quick Links</h2>
          <ul className="space-y-3 text-sm">
            <li>
              <Link className="flex items-center justify-between p-3 bg-white rounded-lg border border-slate-200 hover:border-brand-400 hover:shadow-sm transition-all group" href="/jobs">
                <span className="font-medium text-slate-700 group-hover:text-brand-700">All Jobs</span>
                <span className="text-slate-400 group-hover:text-brand-500">→</span>
              </Link>
            </li>
            <li>
              <Link className="flex items-center justify-between p-3 bg-white rounded-lg border border-slate-200 hover:border-brand-400 hover:shadow-sm transition-all group" href="/scrapers">
                <span className="font-medium text-slate-700 group-hover:text-brand-700">Scraper Registry (Phase 3)</span>
                <span className="text-slate-400 group-hover:text-brand-500">→</span>
              </Link>
            </li>
            <li>
              <Link className="flex items-center justify-between p-3 bg-white rounded-lg border border-slate-200 hover:border-brand-400 hover:shadow-sm transition-all group" href="/evaluation">
                <span className="font-medium text-slate-700 group-hover:text-brand-700">Phase 1 LLM Benchmarks</span>
                <span className="text-slate-400 group-hover:text-brand-500">→</span>
              </Link>
            </li>
            <li>
              <Link className="flex items-center justify-between p-3 bg-white rounded-lg border border-slate-200 hover:border-brand-400 hover:shadow-sm transition-all group" href="/agents">
                <span className="font-medium text-slate-700 group-hover:text-brand-700">Phase 2 CUA Runs</span>
                <span className="text-slate-400 group-hover:text-brand-500">→</span>
              </Link>
            </li>
            <li>
              <Link className="flex items-center justify-between p-3 bg-white rounded-lg border border-rose-200 hover:border-rose-400 hover:shadow-sm transition-all group" href="/admin">
                <span className="font-medium text-slate-700 group-hover:text-rose-700">Admin / Errors</span>
                <span className="text-rose-400 group-hover:text-rose-500">→</span>
              </Link>
            </li>
          </ul>
        </div>
      </section>
    </div>
  );
}
