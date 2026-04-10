import clsx from "clsx";

const styles: Record<string, string> = {
  success: "badge-success",
  failed:  "badge-failed",
  running: "badge-running",
  pending: "badge-pending",
  partial: "badge-partial",
};

export default function StatusBadge({ status }: { status: string }) {
  return <span className={clsx("badge", styles[status] || "badge-pending")}>{status}</span>;
}
