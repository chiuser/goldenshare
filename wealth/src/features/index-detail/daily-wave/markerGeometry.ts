export type DailyWaveDirection = "UP" | "DOWN";

export interface DailyWaveMarkerInput {
  date: string;
  /** Drawing direction only. A shared turn uses the following segment's direction. */
  direction: DailyWaveDirection;
  segmentIds: readonly string[];
}

export interface DailyWaveMarkerIssue extends DailyWaveMarkerInput {
  reason: "COORDINATE_UNAVAILABLE" | "SPACE_UNAVAILABLE";
}

export interface DailyWaveMarkerRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export interface DailyWaveMarkerCoordinate extends DailyWaveMarkerInput {
  x: number | null;
  anchorY: number | null;
}

export interface DailyWaveMarkerLayout extends DailyWaveMarkerInput {
  rect: DailyWaveMarkerRect;
}

export interface DailyWaveLayoutInput {
  markers: readonly DailyWaveMarkerCoordinate[];
  occupied: readonly DailyWaveMarkerRect[];
  width: number;
  height: number;
}

/** Coordinates are CSS pixels. The first clear position wins; dates never move. */
export function resolveDailyWaveMarkerLayout(input: DailyWaveLayoutInput): {
  layouts: DailyWaveMarkerLayout[];
  issues: DailyWaveMarkerIssue[];
} {
  const layouts: DailyWaveMarkerLayout[] = [];
  const issues: DailyWaveMarkerIssue[] = [];
  const occupied = [...input.occupied];
  const ordered = [...input.markers].sort((a, b) =>
    a.date.localeCompare(b.date) || a.direction.localeCompare(b.direction));
  for (const { date, direction, segmentIds, x, anchorY } of ordered) {
    const marker = { date, direction, segmentIds };
    if (x === null || anchorY === null || !Number.isFinite(x) || !Number.isFinite(anchorY)) {
      issues.push({ ...marker, reason: "COORDINATE_UNAVAILABLE" });
      continue;
    }
    let selected: DailyWaveMarkerRect | null = null;
    for (let distance = 8; distance <= 40; distance += 4) {
      const rect = { left: x - 4, top: direction === "UP"
        ? anchorY + distance : anchorY - distance - 6, width: 8, height: 6 };
      if (Number.isFinite(input.width) && Number.isFinite(input.height) &&
          rect.left >= 0 && rect.top >= 0 && rect.left + rect.width <= input.width &&
          rect.top + rect.height <= input.height && !occupied.some((other) => intersects(rect, other))) {
        selected = rect;
        break;
      }
    }
    if (!selected) {
      issues.push({ ...marker, reason: "SPACE_UNAVAILABLE" });
      continue;
    }
    occupied.push(selected);
    layouts.push({ ...marker, rect: selected });
  }
  return { layouts, issues };
}

function intersects(a: DailyWaveMarkerRect, b: DailyWaveMarkerRect): boolean {
  return a.left < b.left + b.width && a.left + a.width > b.left &&
    a.top < b.top + b.height && a.top + a.height > b.top;
}
