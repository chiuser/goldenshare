import { Badge } from "./Badge";
import type { RiskItem } from "../types";

type RiskCardProps = {
  context?: string;
  risk: RiskItem;
};

export function RiskCard({ risk, context }: RiskCardProps) {
  const severityClass = risk.severity.toLowerCase();
  return (
    <article className={`risk-card surface-card ${severityClass}`}>
      <div className="risk-card-header">
        <div>
          <strong>{risk.code}</strong>
          {context ? <em>{context}</em> : null}
        </div>
        <Badge tone={riskSeverityTone(risk.severity)}>{riskSeverityLabel(risk.severity)}</Badge>
      </div>
      <p>{risk.message}</p>
      {risk.path ? <code>{risk.path}</code> : null}
    </article>
  );
}

function riskSeverityLabel(severity: string): string {
  const labels: Record<string, string> = {
    critical: "严重",
    error: "错误",
    warning: "警告",
    info: "提示",
  };
  return labels[severity.toLowerCase()] ?? severity;
}

function riskSeverityTone(severity: string): "success" | "warning" | "error" | "muted" | "brand" {
  const normalized = severity.toLowerCase();
  if (normalized === "critical" || normalized === "error") {
    return "error";
  }
  if (normalized === "warning") {
    return "warning";
  }
  return "muted";
}
