import type {
  SectorRelativeRotationRowViewModel,
  SectorRelativeRotationTrailPointViewModel,
} from "./sectorRelativeRotationTypes";

export const RELATIVE_ROTATION_VIEWBOX = { width: 1088, height: 733 } as const;
export const RELATIVE_ROTATION_PLOT = { left: 68, right: 36, top: 44, bottom: 56 } as const;

export interface RelativeRotationPlotScale {
  readonly xMin: 0;
  readonly xMax: 100;
  readonly yMin: number;
  readonly yMax: number;
  readonly xTicks: readonly [0, 25, 50, 75, 100];
  readonly yTicks: readonly [number, number, 0, number, number];
}

export interface RelativeRotationPixelPoint {
  x: number;
  y: number;
}

export function buildRelativeRotationPlotScale(
  rows: readonly SectorRelativeRotationRowViewModel[],
  trail: readonly SectorRelativeRotationTrailPointViewModel[],
): RelativeRotationPlotScale {
  const values = [
    ...rows.filter((row) => row.coordinateStatus === "PLOTTABLE").map((row) => row.percentileDelta5d),
    ...trail.filter((point) => point.coordinateStatus === "PLOTTABLE").map((point) => point.percentileDelta5d),
  ].filter((value): value is number => value !== null && Number.isFinite(value));
  const raw = Math.max(0, ...values.map(Math.abs));
  const extent = raw === 0 ? 1 : niceCeil(raw * 1.08);
  return Object.freeze({
    xMin: 0 as const,
    xMax: 100 as const,
    yMin: -extent,
    yMax: extent,
    xTicks: [0, 25, 50, 75, 100] as const,
    yTicks: [-extent, -extent / 2, 0, extent / 2, extent] as const,
  });
}

export function toRelativeRotationPixels(percentile: number, delta: number, scale: RelativeRotationPlotScale): RelativeRotationPixelPoint {
  const width = RELATIVE_ROTATION_VIEWBOX.width - RELATIVE_ROTATION_PLOT.left - RELATIVE_ROTATION_PLOT.right;
  const height = RELATIVE_ROTATION_VIEWBOX.height - RELATIVE_ROTATION_PLOT.top - RELATIVE_ROTATION_PLOT.bottom;
  return {
    x: RELATIVE_ROTATION_PLOT.left + (percentile - scale.xMin) / (scale.xMax - scale.xMin) * width,
    y: RELATIVE_ROTATION_PLOT.top + (scale.yMax - delta) / (scale.yMax - scale.yMin) * height,
  };
}

export function buildTrailSegments(
  points: readonly SectorRelativeRotationTrailPointViewModel[],
  scale: RelativeRotationPlotScale,
): RelativeRotationPixelPoint[][] {
  const segments: RelativeRotationPixelPoint[][] = [];
  let current: RelativeRotationPixelPoint[] = [];
  points.forEach((point) => {
    if (point.coordinateStatus !== "PLOTTABLE" || point.percentile === null || point.percentileDelta5d === null) {
      if (current.length > 0) segments.push(current);
      current = [];
      return;
    }
    current.push(toRelativeRotationPixels(point.percentile, point.percentileDelta5d, scale));
  });
  if (current.length > 0) segments.push(current);
  return segments;
}

export function chooseLabelPosition(point: RelativeRotationPixelPoint, width: number, height: number, preferBelow = false) {
  const margin = 8;
  const gap = 10;
  const candidates = preferBelow
    ? [
        { x: point.x + gap, y: point.y + gap },
        { x: point.x - width - gap, y: point.y + gap },
        { x: point.x + gap, y: point.y - height - gap },
        { x: point.x - width - gap, y: point.y - height - gap },
      ]
    : [
        { x: point.x + gap, y: point.y - height - gap },
        { x: point.x - width - gap, y: point.y - height - gap },
        { x: point.x + gap, y: point.y + gap },
        { x: point.x - width - gap, y: point.y + gap },
      ];
  return candidates.find((candidate) => (
    candidate.x >= margin
    && candidate.y >= margin
    && candidate.x + width <= RELATIVE_ROTATION_VIEWBOX.width - margin
    && candidate.y + height <= RELATIVE_ROTATION_VIEWBOX.height - margin
  )) ?? {
    x: Math.min(Math.max(point.x + gap, margin), RELATIVE_ROTATION_VIEWBOX.width - margin - width),
    y: Math.min(Math.max(point.y - height - gap, margin), RELATIVE_ROTATION_VIEWBOX.height - margin - height),
  };
}

export function niceCeil(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const normalized = value / power;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * power;
}
