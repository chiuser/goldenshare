import type {
  CandlestickData,
  HistogramData,
  LineData,
  Time,
  WhitespaceData,
} from "lightweight-charts";

import type { DetailChartPoint } from "./detailChartTypes";

export const DETAIL_CHART_COLORS = {
  amber: "#f59e0b",
  axis: "rgba(148, 163, 184, 0.32)",
  blue: "#5aa7ff",
  brand: "#f7c76b",
  cyan: "#30d5c8",
  down: "#18d092",
  grid: "rgba(148, 163, 184, 0.14)",
  purple: "#b794f4",
  rose: "#fb7185",
  slate: "#cbd5e1",
  text: "#7b8aa0",
  up: "#ff4d5a",
} as const;

export function isFiniteChartNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function buildCandlestickData(points: DetailChartPoint[]): CandlestickData<Time>[] {
  return points.flatMap((point) => {
    if (
      !isFiniteChartNumber(point.open) ||
      !isFiniteChartNumber(point.high) ||
      !isFiniteChartNumber(point.low) ||
      !isFiniteChartNumber(point.close)
    ) {
      return [];
    }
    return [{
      time: point.time as Time,
      open: point.open,
      high: point.high,
      low: point.low,
      close: point.close,
    }];
  });
}

export function buildLineData(
  points: DetailChartPoint[],
  valueOf: (point: DetailChartPoint) => number | null,
): Array<LineData<Time> | WhitespaceData<Time>> {
  return points.map((point) => {
    const value = valueOf(point);
    return isFiniteChartNumber(value)
      ? { time: point.time as Time, value }
      : { time: point.time as Time };
  });
}

export function buildHistogramData(
  points: DetailChartPoint[],
  valueOf: (point: DetailChartPoint) => number | null,
  colorOf: (point: DetailChartPoint, value: number) => string,
): HistogramData<Time>[] {
  return points.flatMap((point) => {
    const value = valueOf(point);
    if (!isFiniteChartNumber(value)) return [];
    return [{ time: point.time as Time, value, color: colorOf(point, value) }];
  });
}
