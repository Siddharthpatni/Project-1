import { ReactNode } from "react";

export default function StatCard({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: string | number;
}) {
  return (
    <div className="card p-5">
      <div className="flex items-center justify-between text-slate-500">
        <span className="text-sm">{label}</span>
        <span className="text-brand-600">{icon}</span>
      </div>
      <div className="mt-2 text-2xl font-semibold">{value}</div>
    </div>
  );
}
