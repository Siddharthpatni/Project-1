import clsx from "clsx";

const STYLES: Record<string, string> = {
  success: "badge badge-success",
  failed:  "badge badge-failed",
  running: "badge badge-running",
  pending: "badge badge-pending",
  partial: "badge badge-partial",
};

const LABELS: Record<string, string> = {
  success: "Success",
  failed:  "Failed",
  running: "Running",
  pending: "Pending",
  partial: "Partial",
};

export default function StatusBadge({ status }: { status: string }) {
  return (
    <span className={clsx(STYLES[status] ?? "badge badge-pending")}>
      {LABELS[status] ?? status}
    </span>
  );
}
