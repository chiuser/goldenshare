import { Badge } from "@mantine/core";
import type { MantineSize } from "@mantine/core";

import { formatStatusLabel } from "../ops-display";

type BadgeTone = "neutral" | "info" | "success" | "warning" | "error";

interface ToneConfig {
  scale: BadgeTone;
  backgroundIndex: number;
  textIndex: number;
  borderIndex: number;
}

const toneMap: Record<string, ToneConfig> = {
  queued: { scale: "neutral", backgroundIndex: 1, textIndex: 7, borderIndex: 3 },
  running: { scale: "info", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  canceling: { scale: "warning", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  success: { scale: "success", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  failed: { scale: "error", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  canceled: { scale: "neutral", backgroundIndex: 1, textIndex: 7, borderIndex: 3 },
  partial_success: { scale: "warning", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  active: { scale: "success", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  paused: { scale: "warning", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  disabled: { scale: "neutral", backgroundIndex: 1, textIndex: 7, borderIndex: 3 },
  previewing: { scale: "info", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  completed: { scale: "success", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  rolled_back: { scale: "warning", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  fresh: { scale: "success", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  lagging: { scale: "warning", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  stale: { scale: "error", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  unknown: { scale: "neutral", backgroundIndex: 1, textIndex: 7, borderIndex: 3 },
  skipped: { scale: "neutral", backgroundIndex: 1, textIndex: 7, borderIndex: 3 },
  unobserved: { scale: "neutral", backgroundIndex: 1, textIndex: 7, borderIndex: 3 },
  info: { scale: "info", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  warning: { scale: "warning", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
  error: { scale: "error", backgroundIndex: 0, textIndex: 6, borderIndex: 2 },
};

export function StatusBadge({
  value,
  label,
  size,
}: {
  value: string | null | undefined;
  label?: string | null;
  size?: MantineSize;
}) {
  return <StatusBadgeWithLabel value={value} label={label} size={size} />;
}

export function StatusBadgeWithLabel({
  value,
  label,
  size,
}: {
  value: string | null | undefined;
  label?: string | null;
  size?: MantineSize;
}) {
  const normalized = (value || "unknown").toLowerCase();
  const tone = toneMap[normalized] || toneMap.unknown;
  return (
    <Badge
      className="status-badge"
      data-status={normalized}
      data-tone={tone.scale}
      size={size}
      radius="sm"
      variant="light"
      styles={(theme) => ({
        root: {
          backgroundColor: theme.colors[tone.scale][tone.backgroundIndex],
          color: theme.colors[tone.scale][tone.textIndex],
          border: `1px solid ${theme.colors[tone.scale][tone.borderIndex]}`,
          fontWeight: 600,
          minWidth: "72px",
          justifyContent: "center",
          letterSpacing: 0,
        },
      })}
    >
      {label || formatStatusLabel(value)}
    </Badge>
  );
}
