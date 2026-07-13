import { ReactNode } from "react";
import { Skeleton } from "@/components/ui";

interface StatCardProps {
  icon?: ReactNode;
  label: string;
  value: ReactNode;
  sub?: string;
  loading?: boolean;
  color?: string;
}

export default function StatCard({ icon, label, value, sub, loading, color }: StatCardProps) {
  return (
    <div className="card p-5 flex flex-col gap-3 hover:shadow-md transition-shadow">
      <div className="flex items-center justify-between">
        <span className="text-label">{label}</span>
        {icon && (
          <span style={{ color: color ?? "var(--brand)", opacity: 0.75 }}>{icon}</span>
        )}
      </div>
      {loading ? (
        <Skeleton height="2rem" width="55%" />
      ) : (
        <span
          className="text-2xl font-extrabold tracking-tight"
          style={{ color: color ?? "var(--fg)" }}
        >
          {value}
        </span>
      )}
      {sub && !loading && (
        <p className="text-xs" style={{ color: "var(--fg-subtle)", marginTop: "-8px" }}>{sub}</p>
      )}
    </div>
  );
}
