/**
 * Shared display formatters.
 *
 * Money was formatted ad hoc across pages (toFixed(3) here, toFixed(4)
 * there), so the same total rendered as $12.117, $12.1168 and $12.005
 * depending on the page. One formatter, one look:
 *   - ≥ $0.01  → standard currency, 2 decimals ($12.12)
 *   - < $0.01  → 4 decimals so tiny per-run LLM costs stay visible ($0.0021)
 */
export function usd(v: number | null | undefined): string {
  const n = v ?? 0;
  if (n !== 0 && Math.abs(n) < 0.01) return `$${n.toFixed(4)}`;
  return n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** Seconds → compact human duration: 0.8s, 12.4s, 3.2m, 1.5h */
export function duration(seconds: number | null | undefined): string {
  const s = seconds ?? 0;
  if (s < 60) return `${s.toFixed(1)}s`;
  if (s < 3600) return `${(s / 60).toFixed(1)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}
