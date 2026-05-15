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
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Vergabepilot.AI</h1>
        <p className="text-slate-600 mt-1">
          Geben Sie Vergabe-URLs ein und lassen Sie die kaskadierte Pipeline (bestehender Scraper → LLM-generiert → CUA-Fallback) den Rest erledigen.
        </p>
      </header>

      <section className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard icon={<Activity className="w-5 h-5" />} label="Jobs"      value={stats?.jobs ?? "—"} />
        <StatCard icon={<CheckCircle2 className="w-5 h-5" />} label="Item success rate"
                  value={stats ? `${Math.round((stats.item_success_rate ?? 0) * 100)}%` : "—"} />
        <StatCard icon={<Cpu className="w-5 h-5" />}      label="Scraper templates" value={stats?.scraper_templates ?? "—"} />
        <StatCard icon={<DollarSign className="w-5 h-5" />} label="LLM spend (USD)" value={stats ? `$${(stats.total_cost_usd ?? 0).toFixed(2)}` : "—"} />
      </section>

      {stats && stats.strategy_distribution && Object.keys(stats.strategy_distribution).length > 0 && (
        <section className="card p-6">
          <h2 className="text-lg font-semibold mb-4">Strategie-Erfolgsraten</h2>
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
                <Tooltip cursor={{ fill: "#f1f5f9" }} formatter={(val) => [`${val}%`, "Erfolgsrate"]} />
                <Bar dataKey="rate" fill="#0d9488" radius={[0, 4, 4, 0]} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="card p-6">
          <h2 className="text-lg font-semibold mb-4">Submit a new scraping job</h2>
          <JobSubmitForm />
        </div>

        <div className="card p-6">
          <h2 className="text-lg font-semibold mb-4">Quick links</h2>
          <ul className="space-y-2 text-sm">
            <li><Link className="text-brand-700 hover:underline" href="/jobs">All jobs →</Link></li>
            <li><Link className="text-brand-700 hover:underline" href="/scrapers">Scraper registry (Phase 3) →</Link></li>
            <li><Link className="text-brand-700 hover:underline" href="/evaluation">Phase 1 LLM benchmarks →</Link></li>
            <li><Link className="text-brand-700 hover:underline" href="/agents">Phase 2 CUA runs →</Link></li>
            <li><Link className="text-brand-700 hover:underline" href="/admin">Admin / errors →</Link></li>
          </ul>
        </div>
      </section>
    </div>
  );
}
