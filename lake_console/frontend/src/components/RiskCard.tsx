import { Badge } from "./Badge";
import type { BadgeTone } from "./Badge";
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
        <div className="risk-card-title">
          <div className="risk-card-code-row">
            <Badge tone={riskSeverityTone(risk.severity)}>{riskSeverityLabel(risk.severity)}</Badge>
            <strong>{risk.code}</strong>
          </div>
          {context ? <em>{context}</em> : null}
        </div>
      </div>
      <p>{risk.message}</p>
      {risk.path ? (
        <div className="risk-card-path">
          <span>路径</span>
          <code>{risk.path}</code>
        </div>
      ) : null}
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

function riskSeverityTone(severity: string): BadgeTone {
  const normalized = severity.toLowerCase();
  if (normalized === "critical" || normalized === "error") {
    return "error";
  }
  if (normalized === "warning") {
    return "warning";
  }
  if (normalized === "info") {
    return "info";
  }
  return "muted";
}
