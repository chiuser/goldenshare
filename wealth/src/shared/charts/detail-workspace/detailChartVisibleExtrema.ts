import type { Time } from "lightweight-charts";

import { isFiniteChartNumber } from "./detailChartSeries";
import type { DetailChartLogicalRange } from "./detailChartViewport";

export interface DetailChartVisibleCandle {
  high: number | null;
  low: number | null;
  time: Time;
}

export interface DetailChartVisibleExtremum {
  index: number;
  time: Time;
  value: number;
}

export interface DetailChartVisibleExtrema {
  high: DetailChartVisibleExtremum | null;
  low: DetailChartVisibleExtremum | null;
}

export interface DetailChartVisibleIndexRange {
  endIndex: number;
  startIndex: number;
}

export function resolveVisibleIndexRange(
  range: DetailChartLogicalRange | null,
  pointCount: number,
): DetailChartVisibleIndexRange | null {
  if (
    !range ||
    !Number.isFinite(range.from) ||
    !Number.isFinite(range.to) ||
    !Number.isFinite(pointCount) ||
    pointCount <= 0
  ) {
    return null;
  }

  const normalizedPointCount = Math.floor(pointCount);
  const startIndex = Math.max(0, Math.ceil(range.from));
  const endIndex = Math.min(normalizedPointCount - 1, Math.floor(range.to));
  return startIndex <= endIndex ? { endIndex, startIndex } : null;
}

export function resolveVisibleExtrema(
  candles: readonly DetailChartVisibleCandle[],
  range: DetailChartLogicalRange | null,
): DetailChartVisibleExtrema {
  const visibleIndexes = resolveVisibleIndexRange(range, candles.length);
  if (!visibleIndexes) return { high: null, low: null };

  let high: DetailChartVisibleExtremum | null = null;
  let low: DetailChartVisibleExtremum | null = null;

  for (let index = visibleIndexes.startIndex; index <= visibleIndexes.endIndex; index += 1) {
    const candle = candles[index];
    if (!candle) continue;

    if (isFiniteChartNumber(candle.high) && (!high || candle.high >= high.value)) {
      high = { index, time: candle.time, value: candle.high };
    }
    if (isFiniteChartNumber(candle.low) && (!low || candle.low <= low.value)) {
      low = { index, time: candle.time, value: candle.low };
    }
  }

  return { high, low };
}
