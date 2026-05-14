import { Badge } from "./Badge";
import type { BadgeTone } from "./Badge";

type HealthBadgeProps = {
  label: string;
  status: string;
};

export function HealthBadge({ label, status }: HealthBadgeProps) {
  const normalized = normalizeHealthStatus(status);
  const tone: BadgeTone = normalized === "ok" ? "success" : normalized === "warning" ? "warning" : normalized === "error" ? "error" : "neutral";
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
