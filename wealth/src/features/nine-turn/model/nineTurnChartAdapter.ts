import type { Time } from "lightweight-charts";

import type { DetailChartPoint, DetailChartTimeMode } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { NineTurnRenderMarker } from "../../../shared/charts/detail-workspace/nineTurnMarkerTypes";
import type { NineTurnMarkerDto } from "../api/nineTurnApiTypes";

export interface NineTurnChartAdaptation {
  droppedMarkerCount: number;
  markers: NineTurnRenderMarker[];
}

export function buildNineTurnRenderMarkers(
  markers: readonly NineTurnMarkerDto[],
  points: readonly DetailChartPoint[],
  timeMode: DetailChartTimeMode,
): NineTurnChartAdaptation {
  const pointsByKey = new Map<string, DetailChartPoint>();
  const duplicateKeys = new Set<string>();
  for (const point of points) {
    const key = pointKey(point, timeMode);
    if (pointsByKey.has(key)) duplicateKeys.add(key);
    else pointsByKey.set(key, point);
  }
  const output: NineTurnRenderMarker[] = [];
  let droppedMarkerCount = 0;
  for (const marker of markers) {
    const key = markerKey(marker, timeMode);
    const point = pointsByKey.get(key);
    const anchorPrice = marker.direction === "UP" ? point?.high : point?.low;
    if (
      duplicateKeys.has(key) || !point ||
      typeof anchorPrice !== "number" || !Number.isFinite(anchorPrice)
    ) {
      droppedMarkerCount += 1;
      continue;
    }
    output.push({
      anchorPrice,
      direction: marker.direction,
      sequenceNumber: marker.sequenceNumber,
      time: point.time as Time,
    });
  }
  return { droppedMarkerCount, markers: output };
}

function pointKey(point: DetailChartPoint, timeMode: DetailChartTimeMode): string {
  if (timeMode === "daily") return point.fullDate.slice(0, 10);
  return String(point.time);
}

function markerKey(marker: NineTurnMarkerDto, timeMode: DetailChartTimeMode): string {
  if (timeMode === "daily") return marker.tradeDate;
  const timestamp = marker.tradeTime === null ? Number.NaN : Date.parse(marker.tradeTime);
  return Number.isFinite(timestamp) ? String(Math.floor(timestamp / 1000)) : "invalid";
}
