import { isFiniteChartNumber } from "./detailChartSeries";
import type { DetailChartPoint } from "./detailChartTypes";
import { resolveVisibleIndexRange } from "./detailChartVisibleExtrema";
import type { DetailChartLogicalRange } from "./detailChartViewport";

export type DetailChartIndicatorField = "macd" | "dif" | "dea" | "k" | "d" | "j";

export interface DetailChartIndicatorRange {
  dataMax: number;
  dataMin: number;
  domainMax: number;
  domainMin: number;
  isDegenerate: boolean;
}

export const MACD_RANGE_FIELDS = ["macd", "dif", "dea"] as const;
export const KDJ_RANGE_FIELDS = ["k", "d", "j"] as const;

export function resolveVisibleIndicatorRange<Field extends DetailChartIndicatorField>(
  points: readonly DetailChartPoint[],
  logicalRange: DetailChartLogicalRange | null,
  fields: readonly Field[],
  valuesOf: (point: DetailChartPoint) => Pick<DetailChartPoint, Field> | null = (point) => point,
): DetailChartIndicatorRange | null {
  const visibleIndexes = resolveVisibleIndexRange(logicalRange, points.length);
  if (!visibleIndexes) return null;

  let dataMin = Number.POSITIVE_INFINITY;
  let dataMax = Number.NEGATIVE_INFINITY;

  for (let index = visibleIndexes.startIndex; index <= visibleIndexes.endIndex; index += 1) {
    const point = points[index];
    if (!point) continue;
    const values = valuesOf(point);
    if (!values) continue;
    for (const field of fields) {
      const value = values[field];
      if (!isFiniteChartNumber(value)) continue;
      dataMin = Math.min(dataMin, value);
      dataMax = Math.max(dataMax, value);
    }
  }

  if (!Number.isFinite(dataMin) || !Number.isFinite(dataMax)) return null;
  if (dataMin !== dataMax) {
    return {
      dataMax,
      dataMin,
      domainMax: dataMax,
      domainMin: dataMin,
      isDegenerate: false,
    };
  }

  const padding = Math.max(Math.abs(dataMin) * 0.01, 0.01);
  return {
    dataMax,
    dataMin,
    domainMax: dataMax + padding,
    domainMin: dataMin - padding,
    isDegenerate: true,
  };
}
