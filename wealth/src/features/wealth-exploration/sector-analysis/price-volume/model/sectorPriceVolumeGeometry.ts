import type { PriceVolumeHistoryPointViewModel, PriceVolumeSnapshotRowViewModel } from "../api/sectorPriceVolumeTypes";

export interface NumericDomain { min: number; max: number }
export interface PlotPoint { sectorCode: string; x: number; y: number }
export interface LinePoint { index: number; x: number; y: number; value: number }

export function buildPaddedDomain(values: number[], includeZero: boolean): NumericDomain {
  const finite = values.filter(Number.isFinite);
  const source = includeZero ? [...finite, 0] : finite;
  if (source.length === 0) return { min: -1, max: 1 };
  const rawMin = Math.min(...source);
  const rawMax = Math.max(...source);
  if (rawMax === rawMin) {
    const padding = Math.max(Math.abs(rawMax) * 0.08, 1);
    return { min: rawMin - padding, max: rawMax + padding };
  }
  const padding = (rawMax - rawMin) * 0.08;
  return { min: rawMin - padding, max: rawMax + padding };
}

export function mapValue(value: number, domain: NumericDomain, start: number, end: number): number {
  return start + ((value - domain.min) / (domain.max - domain.min)) * (end - start);
}

export function buildScatterGeometry(rows: PriceVolumeSnapshotRowViewModel[], width = 924, height = 360) {
  const plotted = rows.filter((row) => row.priceMomentumPct !== null && row.amountActivityPct !== null);
  const xDomain = buildPaddedDomain(plotted.map((row) => row.priceMomentumPct!), true);
  const yDomain = buildPaddedDomain(plotted.map((row) => row.amountActivityPct!), true);
  const left = 52; const right = width - 22; const top = 26; const bottom = height - 34;
  const points: PlotPoint[] = plotted.map((row) => ({
    sectorCode: row.sectorCode,
    x: mapValue(row.priceMomentumPct!, xDomain, left, right),
    y: mapValue(row.amountActivityPct!, yDomain, bottom, top),
  }));
  return {
    width, height, left, right, top, bottom, xDomain, yDomain, points,
    zeroX: mapValue(0, xDomain, left, right),
    zeroY: mapValue(0, yDomain, bottom, top),
  };
}

export function buildHistorySegments(points: PriceVolumeHistoryPointViewModel[], metric: "priceMomentumPct" | "amountActivityPct", width = 924, height = 126) {
  const values = points.map((point) => point[metric]).filter((value): value is number => value !== null);
  const domain = buildPaddedDomain(values, false);
  const left = 48; const right = width - 20; const top = 24; const bottom = height - 24;
  const mapped: Array<LinePoint | null> = points.map((point, index) => {
    const value = point[metric];
    if (value === null) return null;
    const x = points.length <= 1 ? left : left + (index / (points.length - 1)) * (right - left);
    return { index, x, y: mapValue(value, domain, bottom, top), value };
  });
  const segments: LinePoint[][] = [];
  let current: LinePoint[] = [];
  mapped.forEach((point) => {
    if (point) current.push(point);
    else if (current.length) { segments.push(current); current = []; }
  });
  if (current.length) segments.push(current);
  return { width, height, left, right, top, bottom, domain, mapped, segments };
}

export function clientPointToViewBox(clientX: number, clientY: number, rect: DOMRect, width: number, height: number) {
  return {
    x: ((clientX - rect.left) / rect.width) * width,
    y: ((clientY - rect.top) / rect.height) * height,
  };
}
