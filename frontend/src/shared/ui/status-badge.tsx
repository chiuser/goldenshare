import { Badge } from "@mantine/core";

import { formatStatusLabel } from "../ops-display";

const toneMap: Record<string, { background: string; color: string; border: string }> = {
  queued: { background: "rgba(114, 9, 183, 0.12)", color: "#560bad", border: "rgba(114, 9, 183, 0.18)" },
  running: { background: "rgba(67, 97, 238, 0.12)", color: "#3f37c9", border: "rgba(67, 97, 238, 0.18)" },
  success: { background: "rgba(76, 201, 240, 0.16)", color: "#216d90", border: "rgba(76, 201, 240, 0.28)" },
  failed: { background: "rgba(247, 37, 133, 0.12)", color: "#b5179e", border: "rgba(247, 37, 133, 0.18)" },
  canceled: { background: "rgba(86, 11, 173, 0.12)", color: "#560bad", border: "rgba(86, 11, 173, 0.18)" },
  partial_success: { background: "rgba(72, 149, 239, 0.12)", color: "#4361ee", border: "rgba(72, 149, 239, 0.18)" },
  active: { background: "rgba(76, 201, 240, 0.14)", color: "#0f6d95", border: "rgba(76, 201, 240, 0.24)" },
  paused: { background: "rgba(114, 9, 183, 0.12)", color: "#560bad", border: "rgba(114, 9, 183, 0.18)" },
  disabled: { background: "rgba(58, 12, 163, 0.08)", color: "#5c617f", border: "rgba(58, 12, 163, 0.12)" },
  fresh: { background: "rgba(76, 201, 240, 0.16)", color: "#216d90", border: "rgba(76, 201, 240, 0.28)" },
  lagging: { background: "rgba(72, 149, 239, 0.14)", color: "#3558d4", border: "rgba(72, 149, 239, 0.22)" },
  stale: { background: "rgba(247, 37, 133, 0.14)", color: "#b5179e", border: "rgba(247, 37, 133, 0.22)" },
  unknown: { background: "rgba(58, 12, 163, 0.09)", color: "#5f6286", border: "rgba(58, 12, 163, 0.14)" },
  info: { background: "rgba(72, 149, 239, 0.12)", color: "#4361ee", border: "rgba(72, 149, 239, 0.18)" },
  warning: { background: "rgba(114, 9, 183, 0.12)", color: "#560bad", border: "rgba(114, 9, 183, 0.18)" },
  error: { background: "rgba(247, 37, 133, 0.12)", color: "#b5179e", border: "rgba(247, 37, 133, 0.18)" },
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
  const tone = toneMap[normalized] || toneMap.unknown;
  return (
    <Badge
      radius="xl"
      variant="light"
      styles={{
        root: {
          backgroundColor: tone.background,
          color: tone.color,
          border: `1px solid ${tone.border}`,
          fontWeight: 700,
          minWidth: "74px",
          justifyContent: "center",
        },
      }}
    >
      {label || formatStatusLabel(value)}
    </Badge>
  );
}
