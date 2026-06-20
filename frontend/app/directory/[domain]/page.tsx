/**
 * Public tender list for one domain.
 *
 * No authentication required; read-only. Lists the domain's currently-open
 * tenders (title, reference, deadline, status), soonest-closing first, paginated.
 * Each tender links to its existing detail page at /jobs/{job_id}.
 *
 * Data: GET /api/directory/domains/{domain}/tenders?limit&offset
 */
"use client";

import useSWR from "swr";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { api, fetcher } from "@/lib/api";
import type { DirectoryTender, DirectoryTendersResponse } from "@/lib/types";
import {
  ArrowLeft, FileText, CalendarClock, Inbox, AlertCircle, RefreshCw, ChevronLeft, ChevronRight,
} from "lucide-react";

const PAGE_SIZE = 20;

export default function DomainTendersPage() {
  const params = useParams();
  const domain = decodeURIComponent(String(params.domain ?? ""));
  const [offset, setOffset] = useState(0);

  const { data, error, isLoading, mutate } = useSWR<DirectoryTendersResponse>(
    domain
      ? api(`/directory/domains/${encodeURIComponent(domain)}/tenders?limit=${PAGE_SIZE}&offset=${offset}`)
      : null,
    fetcher,
    { refreshInterval: 30000 },
  );

  const tenders = data?.tenders ?? [];
  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE_SIZE, total);
  const canPrev = offset > 0;
  const canNext = offset + PAGE_SIZE < total;

  return (
    <div className="space-y-6 sm:space-y-8">
      <div>
        <Link
          href="/directory"
          className="inline-flex items-center gap-1.5 text-sm font-semibold mb-4"
          style={{ color: "var(--brand)" }}
        >
          <ArrowLeft className="w-4 h-4" aria-hidden="true" /> All domains
        </Link>
        <header className="section-header">
          <div className="min-w-0">
            <h1 className="text-display font-mono break-all">{domain}</h1>
            <p className="mt-1.5 text-sm font-medium" style={{ color: "var(--fg-muted)" }}>
              {total} open tender{total === 1 ? "" : "s"}, soonest-closing first.
            </p>
          </div>
        </header>
      </div>

      {error ? (
        <ErrorState onRetry={() => mutate()} />
      ) : isLoading ? (
        <ListSkeleton />
      ) : tenders.length === 0 ? (
        <EmptyState />
      ) : (
        <>
          <ul className="space-y-3">
            {tenders.map((t) => (
              <TenderRow key={t.item_id} tender={t} />
            ))}
          </ul>

          <nav aria-label="Pagination" className="flex items-center justify-between pt-2">
            <span className="text-xs font-medium" style={{ color: "var(--fg-subtle)" }}>
              Showing {from}–{to} of {total}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                disabled={!canPrev}
                className="btn-secondary btn-sm"
                aria-label="Previous page"
              >
                <ChevronLeft className="w-4 h-4" aria-hidden="true" /> Prev
              </button>
              <button
                onClick={() => setOffset(offset + PAGE_SIZE)}
                disabled={!canNext}
                className="btn-secondary btn-sm"
                aria-label="Next page"
              >
                Next <ChevronRight className="w-4 h-4" aria-hidden="true" />
              </button>
            </div>
          </nav>
        </>
      )}
    </div>
  );
}

function TenderRow({ tender }: { tender: DirectoryTender }) {
  return (
    <li>
      <Link
        href={`/jobs/${tender.job_id}`}
        className="card card-hover block p-4 sm:p-5"
        aria-label={`Open tender: ${tender.title ?? tender.reference ?? "details"}`}
      >
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <FileText className="w-4 h-4 flex-shrink-0 text-indigo-500" aria-hidden="true" />
              <h2 className="font-semibold truncate" style={{ color: "var(--fg)" }} title={tender.title ?? undefined}>
                {tender.title || <span style={{ color: "var(--fg-subtle)" }}>Untitled tender</span>}
              </h2>
            </div>
            {tender.reference && (
              <p className="mt-1 text-xs font-mono" style={{ color: "var(--fg-subtle)" }}>
                Ref: {tender.reference}
              </p>
            )}
          </div>
          <StatusBadge status={tender.status} />
        </div>
        <div className="mt-3 flex items-center gap-1.5 text-xs font-medium" style={{ color: "var(--fg-muted)" }}>
          <CalendarClock className="w-3.5 h-3.5" aria-hidden="true" />
          {tender.deadline ? `Deadline: ${formatDeadline(tender.deadline)}` : "Deadline: not specified"}
        </div>
      </Link>
    </li>
  );
}

function StatusBadge({ status }: { status: DirectoryTender["status"] }) {
  const styles: Record<DirectoryTender["status"], { cls: string; label: string }> = {
    open:             { cls: "bg-emerald-50 text-emerald-700 border-emerald-200", label: "Open" },
    closing_soon:     { cls: "bg-amber-50 text-amber-700 border-amber-200",       label: "Closing soon" },
    deadline_unknown: { cls: "bg-slate-100 text-slate-600 border-slate-200",      label: "Deadline unknown" },
  };
  const s = styles[status] ?? styles.deadline_unknown;
  return <span className={`badge flex-shrink-0 ${s.cls}`}>{s.label}</span>;
}

/** Format an ISO deadline for display. 23:59 is our date-only sentinel — hide it. */
function formatDeadline(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  const date = d.toLocaleDateString("de-DE", { day: "2-digit", month: "short", year: "numeric" });
  if (d.getHours() === 23 && d.getMinutes() === 59) return date;
  const time = d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" });
  return `${date}, ${time}`;
}

function ListSkeleton() {
  return (
    <ul className="space-y-3" aria-busy="true" aria-label="Loading tenders">
      {Array.from({ length: 5 }).map((_, i) => (
        <li key={i} className="card p-5 space-y-3">
          <div className="skeleton-text w-1/2" />
          <div className="skeleton-text w-1/4" />
        </li>
      ))}
    </ul>
  );
}

function EmptyState() {
  return (
    <div className="card flex flex-col items-center justify-center text-center py-16 px-6">
      <Inbox className="w-10 h-10 mb-3" style={{ color: "var(--fg-subtle)" }} aria-hidden="true" />
      <p className="font-semibold" style={{ color: "var(--fg)" }}>No open tenders in this domain</p>
      <p className="mt-1 text-sm" style={{ color: "var(--fg-muted)" }}>
        Tenders appear here while they are published and still within their deadline.
      </p>
    </div>
  );
}

function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="card flex flex-col items-center justify-center text-center py-16 px-6">
      <AlertCircle className="w-10 h-10 mb-3 text-rose-500" aria-hidden="true" />
      <p className="font-semibold" style={{ color: "var(--fg)" }}>Couldn’t load these tenders</p>
      <p className="mt-1 text-sm" style={{ color: "var(--fg-muted)" }}>Please check your connection and try again.</p>
      <button onClick={onRetry} className="btn-secondary btn-sm mt-4">
        <RefreshCw className="w-4 h-4" aria-hidden="true" /> Retry
      </button>
    </div>
  );
}
