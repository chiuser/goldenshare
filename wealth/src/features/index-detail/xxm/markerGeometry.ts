import { eventMarkerLabel } from "./adapter";
import type { XxmMarker } from "./types";

export const XXM_MARKER_STYLE = {
  fontSize: 12, fontWeight: 700, lineHeight: 16, offset: 8, lineGap: 18, dotRadius: 4, padding: 3,
  maxVerticalShift: 40, maxHorizontalShift: 48, horizontalStep: 12, leaderWidth: 1,
} as const;
export interface PositionedMarker { marker: XxmMarker; x: number; y: number }
export interface MarkerLeader { fromX: number; fromY: number; toX: number; toY: number; via: { x: number; y: number }[] }
export interface MarkerLabel {
  marker: XxmMarker; label: string; left: number; top: number; width: number; height: number;
  leader: MarkerLeader | null;
}

function leaderFor(position: PositionedMarker, left: number, top: number, width: number): MarkerLeader {
  const fromX = Math.max(left, Math.min(position.x, left + width));
  const fromY = Math.max(top, Math.min(position.y, top + XXM_MARKER_STYLE.lineHeight));
  const dx = fromX - position.x, dy = fromY - position.y;
  const scale = XXM_MARKER_STYLE.dotRadius / Math.hypot(dx, dy);
  return { fromX, fromY, toX: position.x + dx * scale, toY: position.y + dy * scale, via: [] };
}

function crossesLabel(line: MarkerLeader, box: MarkerLabel): boolean {
  let start = 0, end = 1;
  for (const [origin, delta, min, max] of [
    [line.fromX, line.toX - line.fromX, box.left, box.left + box.width],
    [line.fromY, line.toY - line.fromY, box.top, box.top + box.height],
  ] as const) {
    if (delta === 0) { if (origin < min || origin > max) return false; }
    else {
      const a = (min - origin) / delta, b = (max - origin) / delta;
      start = Math.max(start, Math.min(a, b)); end = Math.min(end, Math.max(a, b));
      if (start > end) return false;
    }
  }
  return true;
}

function crossesDot(line: MarkerLeader, dot: PositionedMarker): boolean {
  const dx = line.toX - line.fromX, dy = line.toY - line.fromY;
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared === 0 ? 0 : Math.max(0, Math.min(1,
    ((dot.x - line.fromX) * dx + (dot.y - line.fromY) * dy) / lengthSquared));
  return Math.hypot(dot.x - line.fromX - t * dx, dot.y - line.fromY - t * dy)
    < XXM_MARKER_STYLE.dotRadius;
}

function routeLeader(label: MarkerLabel, position: PositionedMarker, labels: MarkerLabel[], dots: PositionedMarker[],
  width: number, height: number): MarkerLeader {
  const direct = label.leader!;
  const x = direct.fromX;
  const minY = Math.max(XXM_MARKER_STYLE.padding, Math.min(label.top, position.y) - XXM_MARKER_STYLE.offset);
  const maxY = Math.min(height - XXM_MARKER_STYLE.padding, Math.max(label.top + label.height, position.y) + XXM_MARKER_STYLE.offset);
  const rows = [...new Set([position.y, ...labels.flatMap(other => [other.top - 3, other.top + other.height + 3])])]
    .filter(y => y >= minY && y <= maxY);
  const columns = [...new Set([(x + position.x) / 2, ...labels.flatMap(other => [other.left - 3, other.left + other.width + 3])])]
    .filter(column => column > Math.min(x, position.x) && column < Math.max(x, position.x) && column >= 0 && column <= width);
  const routes: { line: MarkerLeader; length: number }[] = [];
  for (const y of new Set([direct.fromY, label.top, label.top + label.height, label.top + label.height / 2])) {
    const from = { x, y };
    const variants = [[], [{ x: position.x, y }], ...rows.map(row => [{ x, y: row }, { x: position.x, y: row }]),
      ...columns.map(column => [{ x: column, y }, { x: column, y: position.y }])];
    for (const via of variants) {
      const path = [from, ...via, { x: position.x, y: position.y }].filter((p, i, all) => !i || p.x !== all[i - 1]!.x || p.y !== all[i - 1]!.y);
      const end = path.at(-2)!;
      const distance = Math.hypot(end.x - position.x, end.y - position.y);
      if (distance < XXM_MARKER_STYLE.dotRadius) continue;
      const scale = XXM_MARKER_STYLE.dotRadius / distance;
      path[path.length - 1] = { x: position.x + (end.x - position.x) * scale, y: position.y + (end.y - position.y) * scale };
      let length = 0;
      const clear = path.slice(1).every((p, i) => {
        const previous = path[i]!;
        length += Math.hypot(p.x - previous.x, p.y - previous.y);
        const segment: MarkerLeader = { fromX: previous.x, fromY: previous.y, toX: p.x, toY: p.y, via: [] };
        return labels.every(other => other === label || !crossesLabel(segment, other))
          && dots.every(dot => (dot.x === position.x && dot.y === position.y) || !crossesDot(segment, dot));
      });
      if (clear) routes.push({ line: { fromX: from.x, fromY: from.y, toX: path.at(-1)!.x, toY: path.at(-1)!.y, via: path.slice(1, -1) }, length });
    }
  }
  // Overlapping dots can make a clear route impossible; keep the label and its own endpoint.
  return routes.sort((a, b) => a.length - b.length)[0]?.line ?? direct;
}

export function layoutXxmLabels(markers: PositionedMarker[], width: number, height: number,
  measure: (label: string) => number): MarkerLabel[] {
  const result: MarkerLabel[] = [];
  const { padding, lineHeight, dotRadius, offset, maxVerticalShift, maxHorizontalShift, horizontalStep } = XXM_MARKER_STYLE;
  if (height < lineHeight + padding * 2) return result;
  const groups = new Map<string, PositionedMarker[]>();
  for (const marker of markers) {
    const key = String(marker.marker.time);
    const group = groups.get(key) ?? []; group.push(marker); groups.set(key, group);
  }
  const fit = (position: PositionedMarker, label: string, sameBar: boolean): MarkerLabel | null => {
    const measured = measure(label);
    if (measured + XXM_MARKER_STYLE.padding * 2 > width) return null;
    const preferredLeft = position.x - XXM_MARKER_STYLE.dotRadius - XXM_MARKER_STYLE.offset - measured;
    const left = preferredLeft >= XXM_MARKER_STYLE.padding
      ? preferredLeft : position.x + XXM_MARKER_STYLE.dotRadius + XXM_MARKER_STYLE.offset;
    if (left + measured > width - XXM_MARKER_STYLE.padding) return null;
    const side = position.marker.event.direction === "TOP" ? -1 : 1;
    const firstRow = dotRadius + offset + lineHeight / 2;
    const offsets = [0, side * firstRow, -side * firstRow, side * maxVerticalShift, -side * maxVerticalShift];
    const candidates: { left: number; top: number; distance: number; shifted: boolean }[] = [];
    for (let shift = 0; shift <= (sameBar ? 0 : maxHorizontalShift); shift += horizontalStep) {
      for (const vertical of offsets) {
        const top = Math.max(padding, Math.min(position.y + vertical - lineHeight / 2, height - padding - lineHeight));
        const dy = top + lineHeight / 2 - position.y;
        if (Math.abs(dy) > maxVerticalShift) continue;
        candidates.push({ left: left + (preferredLeft >= padding ? -shift : shift), top,
          distance: Math.hypot(shift, dy), shifted: shift !== 0 || dy !== 0 });
      }
    }
    candidates.sort((a, b) => a.distance - b.distance);
    for (const item of candidates) {
      const candidate: MarkerLabel = { marker: position.marker, label, left: item.left, top: item.top,
        width: measured, height: lineHeight, leader: null };
      if (candidate.left < padding || candidate.left + measured > width - padding) continue;
      const clearsLabels = result.every(previous => candidate.left >= previous.left + previous.width + 3 || previous.left >= candidate.left + candidate.width + 3
        || candidate.top >= previous.top + previous.height + 2 || previous.top >= candidate.top + candidate.height + 2);
      const radius = XXM_MARKER_STYLE.dotRadius + XXM_MARKER_STYLE.padding;
      const clearsDots = markers.every(dot => candidate.left >= dot.x + radius || candidate.left + candidate.width <= dot.x - radius
        || candidate.top >= dot.y + radius || candidate.top + candidate.height <= dot.y - radius);
      if (clearsLabels && clearsDots) {
        if (item.shifted) candidate.leader = leaderFor(position, candidate.left, candidate.top, measured);
        return candidate;
      }
    }
    return null;
  };
  // Give edge-constrained groups first choice; never move their underlying event anchors.
  const ordered = [...groups.values()];
  const slack = (group: PositionedMarker[]) => Math.min(...group.map(p => Math.min(p.y, height - p.y)));
  const placed = new Map<PositionedMarker[], MarkerLabel[]>();
  for (const group of [...ordered].sort((a, b) => slack(a) - slack(b))) {
    const start = result.length;
    for (const position of group) {
      const label = fit(position, eventMarkerLabel(position.marker.event), group.length > 1);
      if (label) result.push(label);
      else {
        result.splice(start);
        const compact = group.length > 1 ? fit(group[0]!, `+${group.length}`, true) : null;
        if (compact) result.push(compact);
        break;
      }
    }
    placed.set(group, result.slice(start));
  }
  const labels = ordered.flatMap(group => placed.get(group)!);
  for (const label of labels) if (label.leader) {
    const position = markers.find(dot => dot.marker === label.marker)!;
    label.leader = routeLeader(label, position, labels, markers, width, height);
  }
  return labels;
}
