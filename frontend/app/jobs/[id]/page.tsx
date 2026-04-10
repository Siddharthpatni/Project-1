"use client";

import useSWR from "swr";
import { useParams } from "next/navigation";
import { api, fetcher } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: job } = useSWR(id ? api(`/jobs/${id}`) : null, fetcher, { refreshInterval: 3000 });

  if (!job) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold font-mono">{job.id}</h1>
        <div className="mt-2 flex items-center gap-3 text-sm text-slate-600">
          <StatusBadge status={job.status} />
          <span>{job.completed}/{job.total_urls} URLs</span>
          <span>${(job.cost_usd ?? 0).toFixed(4)}</span>
          <span>{new Date(job.created_at).toLocaleString()}</span>
        </div>
      </header>

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-slate-600">
            <tr>
              <th className="px-4 py-3 font-medium">URL</th>
              <th className="px-4 py-3 font-medium">Strategy</th>
              <th className="px-4 py-3 font-medium">Iters</th>
              <th className="px-4 py-3 font-medium">Runtime</th>
              <th className="px-4 py-3 font-medium">Docs</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {job.items?.map((item: any) => (
              <tr key={item.id} className="border-t border-slate-100">
                <td className="px-4 py-3 max-w-md truncate" title={item.url}>{item.url}</td>
                <td className="px-4 py-3"><code className="text-xs">{item.strategy}</code></td>
                <td className="px-4 py-3">{item.iterations}</td>
                <td className="px-4 py-3">{item.runtime_seconds.toFixed(1)}s</td>
                <td className="px-4 py-3">{item.document_count}</td>
                <td className="px-4 py-3"><StatusBadge status={item.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {job.items?.some((i: any) => i.error_message) && (
        <div className="card p-6">
          <h2 className="text-lg font-semibold mb-3">Errors</h2>
          <ul className="space-y-2 text-sm">
            {job.items.filter((i: any) => i.error_message).map((i: any) => (
              <li key={i.id} className="border-l-4 border-rose-400 pl-3">
                <div className="text-slate-600 truncate">{i.url}</div>
                <pre className="text-xs text-rose-700 whitespace-pre-wrap">{i.error_message}</pre>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
