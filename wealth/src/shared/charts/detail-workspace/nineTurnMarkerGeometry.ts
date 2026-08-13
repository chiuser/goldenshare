import type { Time } from "lightweight-charts";

import type { NineTurnRenderDirection, NineTurnRenderMarker } from "./nineTurnMarkerTypes";

export const NINE_TURN_MARKER_SIZE = 18;
export const NINE_TURN_MARKER_GAP = 8;

export interface NineTurnMarkerRect {
  height: number;
  left: number;
  top: number;
  width: number;
}

export function resolveNineTurnMarkerRect(
  centerX: number,
  anchorY: number,
  direction: NineTurnRenderDirection,
): NineTurnMarkerRect {
  return {
    height: NINE_TURN_MARKER_SIZE,
    left: centerX - NINE_TURN_MARKER_SIZE / 2,
    top: direction === "UP"
      ? anchorY - NINE_TURN_MARKER_GAP - NINE_TURN_MARKER_SIZE
      : anchorY + NINE_TURN_MARKER_GAP,
    width: NINE_TURN_MARKER_SIZE,
  };
}

export function sortNineTurnMarkers(
  markers: readonly NineTurnRenderMarker[],
): NineTurnRenderMarker[] {
  return [...markers].sort((left, right) => compareTime(left.time, right.time));
}

export function sliceNineTurnMarkersByTime(
  markers: readonly NineTurnRenderMarker[],
  fromTime: Time,
  toTime: Time,
): readonly NineTurnRenderMarker[] {
  const from = comparableTime(fromTime);
  const to = comparableTime(toTime);
  const start = lowerBound(markers, from);
  const end = upperBound(markers, to);
  return markers.slice(start, end);
}

function lowerBound(markers: readonly NineTurnRenderMarker[], target: number | string): number {
  let low = 0;
  let high = markers.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (compareComparable(comparableTime(markers[middle]!.time), target) < 0) low = middle + 1;
    else high = middle;
  }
  return low;
}

function upperBound(markers: readonly NineTurnRenderMarker[], target: number | string): number {
  let low = 0;
  let high = markers.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (compareComparable(comparableTime(markers[middle]!.time), target) <= 0) low = middle + 1;
    else high = middle;
  }
  return low;
}

function compareTime(left: Time, right: Time): number {
  return compareComparable(comparableTime(left), comparableTime(right));
}

function compareComparable(left: number | string, right: number | string): number {
  if (typeof left === "number" && typeof right === "number") return left - right;
  return String(left).localeCompare(String(right));
}

function comparableTime(time: Time): number | string {
  if (typeof time === "number" || typeof time === "string") return time;
  return `${time.year.toString().padStart(4, "0")}-${time.month.toString().padStart(2, "0")}-${time.day.toString().padStart(2, "0")}`;
}
