import { Badge } from "./Badge";

type HealthBadgeProps = {
  status: string;
};

export function HealthBadge({ status }: HealthBadgeProps) {
  const label = status === "ok" ? "已落盘" : status === "warning" ? "有风险" : status === "error" ? "异常" : "未落盘";
  const tone = status === "ok" ? "success" : status === "warning" ? "warning" : status === "error" ? "error" : "muted";
  return (
    <Badge className={`health-badge ${status}`} tone={tone}>
      {label}
    </Badge>
  );
}
