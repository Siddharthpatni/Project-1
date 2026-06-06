import clsx from "clsx";

const STYLES: Record<string, string> = {
  success: "badge-success",
  failed:  "badge-failed",
  running: "badge-running",
  pending: "badge-pending",
  partial: "badge-partial",
};

const LABELS: Record<string, string> = {
  success: "Success",
  failed:  "Failed",
  running: "Running",
  pending: "Pending",
  partial: "Partial",
};

const DOTS: Record<string, string> = {
  success: "bg-emerald-500",
  failed:  "bg-rose-500",
  running: "bg-amber-500 animate-pulse",
  pending: "bg-slate-400",
  partial: "bg-sky-500",
};

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span className={clsx("badge", STYLES[status] ?? "badge-pending")}>
      <span className={clsx("w-1.5 h-1.5 rounded-full inline-block", DOTS[status] ?? "bg-slate-400")} />
      {LABELS[status] ?? status}
    </span>
  );
}
