import { eventMarkerLabel } from "./adapter";
import type { XxmMarker } from "./types";

export const XXM_MARKER_STYLE = {
  fontSize: 12, fontWeight: 700, lineHeight: 16, offset: 8, lineGap: 18, dotRadius: 4, padding: 3,
} as const;
export interface PositionedMarker { marker: XxmMarker; x: number; y: number }
export interface MarkerLabel { marker: XxmMarker; label: string; left: number; top: number; width: number; height: number }

export function layoutXxmLabels(markers: PositionedMarker[], width: number, height: number,
  measure: (label: string) => number): MarkerLabel[] {
  const result: MarkerLabel[] = [];
  const groups = new Map<string, PositionedMarker[]>();
  for (const marker of markers) {
    const key = String(marker.marker.time);
    const group = groups.get(key) ?? []; group.push(marker); groups.set(key, group);
  }
  const fit = (position: PositionedMarker, label: string): MarkerLabel | null => {
    const measured = measure(label);
    if (measured + XXM_MARKER_STYLE.padding * 2 > width) return null;
    const preferredLeft = position.x - XXM_MARKER_STYLE.dotRadius - XXM_MARKER_STYLE.offset - measured;
    const left = preferredLeft >= XXM_MARKER_STYLE.padding
      ? preferredLeft : position.x + XXM_MARKER_STYLE.dotRadius + XXM_MARKER_STYLE.offset;
    if (left + measured > width - XXM_MARKER_STYLE.padding) return null;
    const side = position.marker.event.direction === "TOP" ? -1 : 1;
    const offsets = [0];
    for (const direction of [side, -side]) for (let row = 0; row < Math.ceil(height / XXM_MARKER_STYLE.lineGap); row += 1) {
      offsets.push(direction * (XXM_MARKER_STYLE.dotRadius + XXM_MARKER_STYLE.offset + XXM_MARKER_STYLE.lineHeight / 2 + row * XXM_MARKER_STYLE.lineGap));
    }
    for (const offset of offsets) {
      const top = position.y + offset - XXM_MARKER_STYLE.lineHeight / 2;
      const candidate = { marker: position.marker, label, left, top, width: measured, height: XXM_MARKER_STYLE.lineHeight };
      if (top < XXM_MARKER_STYLE.padding || top + candidate.height > height - XXM_MARKER_STYLE.padding) continue;
      const clearsLabels = result.every(previous => candidate.left >= previous.left + previous.width + 3 || previous.left >= candidate.left + candidate.width + 3
        || candidate.top >= previous.top + previous.height + 2 || previous.top >= candidate.top + candidate.height + 2);
      const radius = XXM_MARKER_STYLE.dotRadius + XXM_MARKER_STYLE.padding;
      const clearsDots = markers.every(dot => candidate.left >= dot.x + radius || candidate.left + candidate.width <= dot.x - radius
        || candidate.top >= dot.y + radius || candidate.top + candidate.height <= dot.y - radius);
      if (clearsLabels && clearsDots) return candidate;
    }
    return null;
  };
  for (const group of groups.values()) {
    const start = result.length;
    for (const position of group) {
      const label = fit(position, eventMarkerLabel(position.marker.event));
      if (label) result.push(label);
      else {
        result.splice(start);
        const compact = fit(group[0]!, `+${group.length}`);
        if (compact) result.push(compact);
        break;
      }
    }
  }
  return result;
}
