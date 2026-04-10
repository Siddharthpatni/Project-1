"use client";

import useSWR from "swr";
import { api, fetcher } from "@/lib/api";

export default function ScrapersPage() {
  const { data: scrapers } = useSWR(api("/scrapers"), fetcher, { refreshInterval: 8000 });

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold">Scraper Registry</h1>
        <p className="text-slate-600 mt-1 text-sm">
          Phase 3: reusable scrapers keyed by domain. Auto-promoted from successful Phase 1 runs.
        </p>
      </header>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-3 font-medium">Domain</th>
              <th className="px-4 py-3 font-medium">Source</th>
              <th className="px-4 py-3 font-medium">Successes</th>
              <th className="px-4 py-3 font-medium">Failures</th>
              <th className="px-4 py-3 font-medium">Avg runtime</th>
              <th className="px-4 py-3 font-medium">Created</th>
            </tr>
          </thead>
          <tbody>
            {scrapers?.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-6 text-center text-slate-500">Registry is empty.</td></tr>
            )}
            {scrapers?.map((s: any) => {
              const total = s.success_count + s.failure_count;
              const rate = total ? Math.round((s.success_count / total) * 100) : 0;
              return (
                <tr key={s.id} className="border-t border-slate-100">
                  <td className="px-4 py-3 font-mono text-xs">{s.domain}</td>
                  <td className="px-4 py-3">{s.source}</td>
                  <td className="px-4 py-3 text-emerald-700">{s.success_count} ({rate}%)</td>
                  <td className="px-4 py-3 text-rose-700">{s.failure_count}</td>
                  <td className="px-4 py-3">{s.avg_runtime?.toFixed(1)}s</td>
                  <td className="px-4 py-3 text-slate-600">{new Date(s.created_at).toLocaleDateString()}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
