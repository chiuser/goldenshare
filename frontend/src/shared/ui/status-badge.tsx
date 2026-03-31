import { Badge } from "@mantine/core";

import { formatStatusLabel } from "../ops-display";

const colorMap: Record<string, string> = {
  queued: "gray",
  running: "blue",
  success: "green",
  failed: "red",
  canceled: "orange",
  partial_success: "yellow",
  active: "green",
  paused: "orange",
  disabled: "gray",
  fresh: "green",
  lagging: "yellow",
  stale: "red",
  unknown: "gray",
  info: "blue",
  warning: "yellow",
  error: "red",
};

export function StatusBadge({
  value,
  label,
}: {
  value: string | null | undefined;
  label?: string | null;
}) {
  return <StatusBadgeWithLabel value={value} label={label} />;
}

export function StatusBadgeWithLabel({
  value,
  label,
}: {
  value: string | null | undefined;
  label?: string | null;
}) {
  const normalized = (value || "unknown").toLowerCase();
  return (
    <Badge color={colorMap[normalized] || "gray"} radius="sm" variant="light">
      {label || formatStatusLabel(value)}
    </Badge>
  );
}
