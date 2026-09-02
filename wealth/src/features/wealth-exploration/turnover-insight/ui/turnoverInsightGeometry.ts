import type { TurnoverInsightAxisViewModel } from "../model/turnoverInsightTypes";

export interface TurnoverInsightChartGeometry {
  width: number;
  height: number;
  plotLeft: number;
  plotRight: number;
  upperTop: number;
  upperBottom: number;
  lowerTop: number;
  lowerBottom: number;
  timeLabelY: number;
}

export type TurnoverInsightLayout = "full" | "compact";

export function buildTurnoverInsightGeometry(
  width: number,
  layout: TurnoverInsightLayout = "full",
): TurnoverInsightChartGeometry {
  const safeWidth = Math.max(360, width);
  if (layout === "compact") {
    return {
      width: safeWidth,
      height: 484,
      plotLeft: 46,
      plotRight: Math.max(66, safeWidth - 22),
      upperTop: 120,
      upperBottom: 300,
      lowerTop: 350,
      lowerBottom: 416,
      timeLabelY: 466,
    };
  }
  return {
    width: safeWidth,
    height: 420,
    plotLeft: 58,
    plotRight: Math.max(78, safeWidth - 30),
    upperTop: 96,
    upperBottom: 270,
    lowerTop: 318,
    lowerBottom: 392,
    timeLabelY: 408,
  };
}

export function xForIndex(
  geometry: TurnoverInsightChartGeometry,
  index: number,
  pointCount: number,
): number {
  if (pointCount <= 1) return geometry.plotLeft;
  return geometry.plotLeft + index * ((geometry.plotRight - geometry.plotLeft) / (pointCount - 1));
}

export function indexForX(
  geometry: TurnoverInsightChartGeometry,
  x: number,
  pointCount: number,
): number {
  if (pointCount <= 1) return 0;
  const ratio = (x - geometry.plotLeft) / (geometry.plotRight - geometry.plotLeft);
  return Math.max(0, Math.min(pointCount - 1, Math.round(ratio * (pointCount - 1))));
}

export function yForValue(
  value: number,
  axis: TurnoverInsightAxisViewModel,
  top: number,
  bottom: number,
): number {
  if (axis.maxYi === axis.minYi) throw new Error("turnover insight axis cannot have zero span");
  return bottom - ((value - axis.minYi) / (axis.maxYi - axis.minYi)) * (bottom - top);
}
