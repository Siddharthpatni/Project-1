"use client";

import useSWR from "swr";
import { api, fetcher } from "@/lib/api";

export default function AdminPage() {
  const { data: stats } = useSWR(api("/admin/stats"), fetcher, { refreshInterval: 5000 });
  const { data: errors } = useSWR(api("/admin/errors"), fetcher, { refreshInterval: 5000 });

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Admin / Ops</h1>

      <div className="card p-6">
        <h2 className="font-semibold mb-3">Strategy distribution</h2>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
          {stats?.strategy_distribution &&
            Object.entries(stats.strategy_distribution).map(([k, v]: any) => (
              <div key={k} className="border border-slate-200 rounded-lg p-3">
                <div className="text-slate-500 text-xs font-mono">{k}</div>
                <div className="text-2xl font-semibold">{v}</div>
              </div>
            ))}
        </div>
      </div>

      <div className="card p-6">
        <h2 className="font-semibold mb-3">Recent failures</h2>
        {errors?.length === 0 && <p className="text-sm text-slate-500">No failures recorded.</p>}
        <ul className="space-y-3 text-sm">
          {errors?.map((e: any) => (
            <li key={e.id} className="border-l-4 border-rose-400 pl-3">
              <div className="text-slate-700 truncate">{e.url}</div>
              <div className="text-xs text-slate-500">
                strategy: <code>{e.strategy}</code> · iterations: {e.iterations}
              </div>
              <pre className="text-xs text-rose-700 whitespace-pre-wrap mt-1">{e.error_message}</pre>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
