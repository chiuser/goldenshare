export interface TrendChannelPoint {
  time: string;
  close: number;
  shortUpper: number;
  shortLower: number;
  longUpper: number;
  longLower: number;
}

export type TrendChannelTone = "short-above" | "short-below" | "long-above" | "long-below";

export const TREND_CHANNEL_COLORS: Record<TrendChannelTone, string> = {
  "short-above": "#ef4444",
  "short-below": "#22c55e",
  "long-above": "#ec4899",
  "long-below": "#3b82f6",
};

export interface TrendChannelLine {
  color: string;
  fromLogical: number;
  fromTime: string;
  fromValue: number;
  toLogical: number;
  toTime: string;
  toValue: number;
  tone: TrendChannelTone;
}

export function buildTrendChannelLines(
  points: TrendChannelPoint[],
  candleTimes: string[],
): TrendChannelLine[] {
  const candleIndex = new Map(candleTimes.map((time, index) => [time, index]));
  const usable = points
    .map((point) => ({ point, logical: candleIndex.get(point.time) }))
    .filter((entry): entry is { point: TrendChannelPoint; logical: number } => entry.logical !== undefined);
  const lines: TrendChannelLine[] = [];

  usable.forEach((entry, index) => {
    appendBand(lines, entry.point, entry.logical, "short");
    appendBand(lines, entry.point, entry.logical, "long");
    const next = usable[index + 1];
    if (!next || next.logical !== entry.logical + 1) return;
    appendConnection(lines, entry, next, "short");
    appendConnection(lines, entry, next, "long");
  });
  return lines;
}

export function resolveTrendTone(point: TrendChannelPoint, band: "short" | "long"): TrendChannelTone {
  const lower = band === "short" ? point.shortLower : point.longLower;
  return `${band}-${point.close < lower ? "below" : "above"}`;
}

function appendBand(
  lines: TrendChannelLine[],
  point: TrendChannelPoint,
  logical: number,
  band: "short" | "long",
) {
  const tone = resolveTrendTone(point, band);
  lines.push({
    color: TREND_CHANNEL_COLORS[tone],
    fromLogical: logical,
    fromTime: point.time,
    fromValue: band === "short" ? point.shortUpper : point.longUpper,
    toLogical: logical,
    toTime: point.time,
    toValue: band === "short" ? point.shortLower : point.longLower,
    tone,
  });
}

function appendConnection(
  lines: TrendChannelLine[],
  current: { point: TrendChannelPoint; logical: number },
  next: { point: TrendChannelPoint; logical: number },
  band: "short" | "long",
) {
  const tone = resolveTrendTone(current.point, band);
  const color = TREND_CHANNEL_COLORS[tone];
  const currentUpper = band === "short" ? current.point.shortUpper : current.point.longUpper;
  const currentLower = band === "short" ? current.point.shortLower : current.point.longLower;
  const nextUpper = band === "short" ? next.point.shortUpper : next.point.longUpper;
  const nextLower = band === "short" ? next.point.shortLower : next.point.longLower;
  lines.push(
    {
      color,
      fromLogical: current.logical,
      fromTime: current.point.time,
      fromValue: currentUpper,
      toLogical: next.logical,
      toTime: next.point.time,
      toValue: nextUpper,
      tone,
    },
    {
      color,
      fromLogical: current.logical,
      fromTime: current.point.time,
      fromValue: currentLower,
      toLogical: next.logical,
      toTime: next.point.time,
      toValue: nextLower,
      tone,
    },
  );
}
