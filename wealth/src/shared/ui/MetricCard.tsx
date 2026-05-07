import type { ReactNode } from "react";

interface MetricCardProps {
  label: string;
  value: ReactNode;
  sub: string;
  className?: string;
}

export function MetricCard({ label, value, sub, className }: MetricCardProps) {
  return (
    <div className={["metric-card", className].filter(Boolean).join(" ")}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-sub">{sub}</div>
    </div>
  );
}
