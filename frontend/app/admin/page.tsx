"use client";

import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { AlertTriangle, Activity, Database, Clock, RefreshCcw, ShieldAlert } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, ResponsiveContainer, Tooltip } from "recharts";

export default function AdminPage() {
  const { data: stats, mutate: mutateStats } = useSWR(api("/admin/stats"), fetcher, { refreshInterval: 10000 });
  const { data: errors, mutate: mutateErrors } = useSWR(api("/admin/errors"), fetcher, { refreshInterval: 10000 });

  return (
    <div className="space-y-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <ShieldAlert className="w-6 h-6 text-brand-600" />
            Admin &amp; Operations
          </h1>
          <p className="text-slate-600 text-sm mt-1">System-wide statistics and recent failures.</p>
        </div>
        <button 
          onClick={() => { mutateStats(); mutateErrors(); }}
          className="p-2 text-slate-500 hover:bg-slate-100 rounded-lg transition"
          title="Refresh Data"
        >
          <RefreshCcw className="w-4 h-4" />
        </button>
      </header>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Strategy Distribution Chart */}
        <div className="card p-6 flex flex-col">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <Activity className="w-4 h-4 text-brand-500" />
            Strategy Distribution
          </h2>
          <div className="flex-1 min-h-[250px]">
            {stats?.strategy_distribution && Object.keys(stats.strategy_distribution).length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={Object.entries(stats.strategy_distribution).map(([k, v]) => ({
                    strategy: k.replace(/_/g, " "),
                    count: v as number
                  }))}
                  margin={{ top: 10, right: 10, left: 0, bottom: 20 }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="strategy" tick={{ fill: "#475569", fontSize: 10 }} angle={-20} textAnchor="end" />
                  <YAxis tick={{ fill: "#475569", fontSize: 10 }} />
                  <Tooltip cursor={{ fill: "#f1f5f9" }} />
                  <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-slate-400 text-sm">No data available</div>
            )}
          </div>
        </div>

        {/* Database Stats */}
        <div className="card p-6">
          <h2 className="font-semibold mb-4 flex items-center gap-2">
            <Database className="w-4 h-4 text-brand-500" />
            Database Overview
          </h2>
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-slate-50 p-4 rounded-xl border border-slate-100">
              <div className="text-xs font-medium text-slate-500 mb-1">Total Jobs</div>
              <div className="text-3xl font-bold text-slate-800">{stats?.jobs ?? "—"}</div>
            </div>
            <div className="bg-slate-50 p-4 rounded-xl border border-slate-100">
              <div className="text-xs font-medium text-slate-500 mb-1">Total Items</div>
              <div className="text-3xl font-bold text-slate-800">{stats?.items ?? "—"}</div>
            </div>
            <div className="bg-slate-50 p-4 rounded-xl border border-slate-100">
              <div className="text-xs font-medium text-slate-500 mb-1">Scraper Templates</div>
              <div className="text-3xl font-bold text-slate-800">{stats?.scraper_templates ?? "—"}</div>
            </div>
            <div className="bg-slate-50 p-4 rounded-xl border border-slate-100">
              <div className="text-xs font-medium text-slate-500 mb-1">LLM Cost</div>
              <div className="text-3xl font-bold text-emerald-600">${(stats?.total_cost_usd ?? 0).toFixed(2)}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="card overflow-hidden">
        <div className="p-4 border-b border-slate-100 bg-rose-50/30 flex justify-between items-center">
          <h2 className="font-semibold flex items-center gap-2 text-rose-800">
            <AlertTriangle className="w-4 h-4" />
            Recent Failures
          </h2>
          <span className="text-xs font-medium bg-rose-100 text-rose-700 px-2 py-0.5 rounded-full">
            {errors?.length ?? 0} Logged
          </span>
        </div>
        
        {(!errors || errors.length === 0) ? (
          <div className="p-8 text-center text-slate-400">No recent failures. System is healthy!</div>
        ) : (
          <ul className="divide-y divide-slate-100 max-h-[600px] overflow-y-auto">
            {errors.map((e: any) => (
              <li key={e.id} className="p-4 hover:bg-slate-50 transition-colors">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-2">
                  <div className="font-mono text-xs text-slate-700 truncate max-w-xl bg-slate-100 px-2 py-1 rounded" title={e.url}>
                    {e.url}
                  </div>
                  <div className="flex items-center gap-2 text-xs">
                    <span className="bg-slate-200 text-slate-700 px-2 py-0.5 rounded-full font-medium">
                      {e.strategy}
                    </span>
                    <span className="flex items-center gap-1 text-slate-500">
                      <Clock className="w-3 h-3" />
                      Iter {e.iterations}
                    </span>
                  </div>
                </div>
                <pre className="text-xs text-rose-600 bg-rose-50/50 p-3 rounded-lg border border-rose-100 whitespace-pre-wrap font-mono mt-2 overflow-x-auto">
                  {e.error_message}
                </pre>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
