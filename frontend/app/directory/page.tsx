/**
 * Public tender directory — browse every domain that has open tenders.
 *
 * No authentication required; read-only. Lists each procurement domain with its
 * count of currently-open tenders. Clicking a domain opens its tender list.
 *
 * Data: GET /api/directory/domains
 */
"use client";

import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import type { DirectoryDomain } from "@/lib/types";
import { Globe, Building2, Inbox, AlertCircle, RefreshCw, ExternalLink } from "lucide-react";

export default function DirectoryPage() {
  const { data, error, isLoading, mutate } = useSWR<{ domains: DirectoryDomain[] }>(
    api("/directory/domains"),
    fetcher,
    { refreshInterval: 30000 },
  );

  const domains = data?.domains ?? [];

  return (
    <div className="space-y-6 sm:space-y-8">
      <header className="section-header">
        <div>
          <h1 className="text-display flex items-center gap-3">
            <Globe className="w-8 h-8 text-indigo-600" aria-hidden="true" />
            Tender Directory
          </h1>
          <p className="mt-1.5 text-sm sm:text-base font-medium" style={{ color: "var(--fg-muted)" }}>
            Pick a procurement domain to open its official portal, where all its tenders are listed.
          </p>
        </div>
      </header>

      {error ? (
        <ErrorState onRetry={() => mutate()} />
      ) : isLoading ? (
        <GridSkeleton />
      ) : domains.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {domains.map((d) => (
            <li key={d.domain}>
              <a
                href={d.site_url}
                target="_blank"
                rel="noopener noreferrer"
                className="card card-hover block p-5 group"
                aria-label={`Open the official ${d.domain} tender portal in a new tab (${d.open_count} open tender${d.open_count === 1 ? "" : "s"})`}
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <Building2 className="w-5 h-5 flex-shrink-0 text-indigo-500" aria-hidden="true" />
                  <span
                    className="font-mono text-sm font-bold truncate"
                    style={{ color: "var(--fg)" }}
                    title={d.domain}
                  >
                    {d.domain}
                  </span>
                  <ExternalLink
                    className="w-3.5 h-3.5 flex-shrink-0 ml-auto opacity-40 group-hover:opacity-100 transition-opacity"
                    style={{ color: "var(--brand)" }}
                    aria-hidden="true"
                  />
                </div>
                <div className="mt-4 flex items-center gap-2">
                  {d.open_count > 0 ? (
                    <span className="badge bg-emerald-50 text-emerald-700 border-emerald-200">
                      {d.open_count} open
                    </span>
                  ) : (
                    <span className="badge bg-slate-100 text-slate-600 border-slate-200">Portal</span>
                  )}
                  <span
                    className="ml-auto text-xs font-semibold opacity-0 group-hover:opacity-100 transition-opacity"
                    style={{ color: "var(--brand)" }}
                    aria-hidden="true"
                  >
                    Visit site ↗
                  </span>
                </div>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function GridSkeleton() {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4" aria-busy="true" aria-label="Loading domains">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="card p-5 space-y-4">
          <div className="skeleton-text w-2/3" />
          <div className="skeleton h-6 w-20 rounded-full" />
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="card flex flex-col items-center justify-center text-center py-16 px-6">
      <Inbox className="w-10 h-10 mb-3" style={{ color: "var(--fg-subtle)" }} aria-hidden="true" />
      <p className="font-semibold" style={{ color: "var(--fg)" }}>No domains with open tenders yet</p>
      <p className="mt-1 text-sm" style={{ color: "var(--fg-muted)" }}>
        Once tenders are scraped and still within their deadline, they’ll appear here.
      </p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="card flex flex-col items-center justify-center text-center py-16 px-6">
      <AlertCircle className="w-10 h-10 mb-3 text-rose-500" aria-hidden="true" />
      <p className="font-semibold" style={{ color: "var(--fg)" }}>Couldn’t load the directory</p>
      <p className="mt-1 text-sm" style={{ color: "var(--fg-muted)" }}>Please check your connection and try again.</p>
      <button onClick={onRetry} className="btn-secondary btn-sm mt-4">
        <RefreshCw className="w-4 h-4" aria-hidden="true" /> Retry
      </button>
    </div>
  );
}
