import type { TrendChannelRawResponse } from "./trendChannelApiClient";
import type { TrendChannelPoint, TrendChannelViewModel } from "../model/indexDetailTypes";

export function buildTrendChannelViewModel(payload: TrendChannelRawResponse): TrendChannelViewModel {
  const points: TrendChannelPoint[] = [];
  let droppedCount = 0;
  let previousTime = "";
  const seen = new Set<string>();

  for (const bar of payload.bars) {
    const point = parsePoint(bar);
    if (!point || seen.has(point.time) || (previousTime && point.time <= previousTime)) {
      droppedCount += 1;
      continue;
    }
    seen.add(point.time);
    previousTime = point.time;
    points.push(point);
  }

  return {
    points,
    droppedCount,
    status: points.length === 0 ? "EMPTY" : droppedCount > 0 ? "PARTIAL" : "READY",
  };
}

function parsePoint(bar: TrendChannelRawResponse["bars"][number]): TrendChannelPoint | null {
  const point = {
    time: toIsoDate(bar.trade_date),
    close: Number(bar.close),
    shortUpper: Number(bar.short_channel.upper),
    shortLower: Number(bar.short_channel.lower),
    longUpper: Number(bar.long_channel.upper),
    longLower: Number(bar.long_channel.lower),
  };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(point.time)) return null;
  if (![point.close, point.shortUpper, point.shortLower, point.longUpper, point.longLower].every(Number.isFinite)) return null;
  if (point.shortUpper < point.shortLower || point.longUpper < point.longLower) return null;
  return point;
}

function toIsoDate(value: string): string {
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  return value;
}
