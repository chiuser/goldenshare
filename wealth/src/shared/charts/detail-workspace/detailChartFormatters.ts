import type { IChartApi, Time } from "lightweight-charts";

import type { DetailChartPoint, DetailChartTimeAxisMarker } from "./detailChartTypes";

export function formatPriceAxisValue(value: number): string {
  return value.toFixed(2);
}

export function formatSignedAxisValue(value: number): string {
  return value.toFixed(2);
}

export function formatCompactAxisValue(value: number): string {
  const absValue = Math.abs(value);
  if (absValue >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (absValue >= 1_000) return `${(value / 1_000).toFixed(2)}K`;
  return value.toFixed(0);
}

export function formatCrosshairDateLabel(point: DetailChartPoint): string {
  return point.fullDate.replaceAll("-", "");
}

export function buildDailyTimeAxisMarkers(
  points: DetailChartPoint[],
  chart: IChartApi,
): DetailChartTimeAxisMarker[] {
  const markers: DetailChartTimeAxisMarker[] = [];
  const visibleRange = chart.timeScale().getVisibleLogicalRange();
  const fromIndex = visibleRange ? Math.max(0, Math.floor(visibleRange.from)) : 0;
  const toIndex = visibleRange ? Math.min(points.length - 1, Math.ceil(visibleRange.to)) : points.length - 1;
  let previousMonth = "";

  for (let index = fromIndex; index <= toIndex; index += 1) {
    const point = points[index];
    if (!point) continue;
    const yearMonth = getYearMonth(point);
    if (!yearMonth) continue;
    const isFirstPoint = index === fromIndex;
    const isNewMonth = yearMonth.month !== previousMonth;
    if (!isFirstPoint && !isNewMonth) continue;

    const coordinate = chart.timeScale().timeToCoordinate(point.time as Time);
    if (coordinate === null) continue;

    markers.push({
      key: point.time,
      label: isFirstPoint ? `${yearMonth.year}/${yearMonth.month}` : yearMonth.month,
      left: coordinate,
      tone: isFirstPoint ? "year" : "month",
    });
    previousMonth = yearMonth.month;
  }

  return markers;
}

function getYearMonth(point: DetailChartPoint): { month: string; year: string } | null {
  const match = point.fullDate.match(/^(\d{4})-(\d{2})-/);
  if (!match) return null;
  return { year: match[1] ?? "", month: match[2] ?? "" };
}
