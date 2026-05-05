import { Badge } from "./Badge";

type HealthBadgeProps = {
  status: string;
};

export function HealthBadge({ status }: HealthBadgeProps) {
  const normalized = normalizeHealthStatus(status);
  const label = normalized === "ok" ? "已落盘" : normalized === "warning" ? "有风险" : normalized === "error" ? "异常" : "未落盘";
  const tone = normalized === "ok" ? "success" : normalized === "warning" ? "warning" : normalized === "error" ? "error" : "muted";
  return (
    <Badge className={`health-badge ${normalized}`} tone={tone}>
      {label}
    </Badge>
  );
}

function normalizeHealthStatus(status: string): "ok" | "warning" | "error" | "empty" {
  if (status === "ok" || status === "warning" || status === "error") {
    return status;
  }
  return "empty";
}
