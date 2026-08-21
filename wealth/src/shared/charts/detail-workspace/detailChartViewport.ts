export const MIN_VISIBLE_BARS = 45;
export const MAX_VISIBLE_BARS = 180;
export const ZOOM_STEP_BARS = 15;
export const DEFAULT_VISIBLE_BARS = 120;
export const MIN_ADAPTIVE_DEFAULT_BARS = 75;
export const MAX_ADAPTIVE_DEFAULT_BARS = 150;
export const TARGET_PIXELS_PER_BAR = 9.5;
export const RIGHT_PRICE_SCALE_WIDTH = 56;
export const LATEST_RANGE_TOLERANCE = 0.5;

export interface DetailChartLogicalRange {
  from: number;
  to: number;
}

export interface DetailChartZoomAvailability {
  canZoomIn: boolean;
  canZoomOut: boolean;
}

export function resolveSharedRightPriceScaleWidth(
  measuredWidths: readonly number[],
  minimumWidth = RIGHT_PRICE_SCALE_WIDTH,
): number {
  const normalizedMinimumWidth = Number.isFinite(minimumWidth) && minimumWidth >= 1
    ? Math.ceil(minimumWidth)
    : RIGHT_PRICE_SCALE_WIDTH;
  return measuredWidths.reduce((maximum, width) => (
    Number.isFinite(width) && width > 0
      ? Math.max(maximum, Math.ceil(width))
      : maximum
  ), normalizedMinimumWidth);
}

export function resolveDetailChartPlotWidth(
  hostWidth: number,
  rightPriceScaleWidth: number,
): number {
  if (!Number.isFinite(hostWidth) || hostWidth <= 0) return 1;
  const normalizedRightPriceScaleWidth = Number.isFinite(rightPriceScaleWidth) && rightPriceScaleWidth > 0
    ? rightPriceScaleWidth
    : RIGHT_PRICE_SCALE_WIDTH;
  return Math.max(1, hostWidth - normalizedRightPriceScaleWidth);
}

export function resolveAdaptiveVisibleCount(
  klineHostWidth: number,
  pointCount: number,
  rightPriceScaleWidth = RIGHT_PRICE_SCALE_WIDTH,
): number {
  if (!Number.isFinite(pointCount) || pointCount <= 0) return 0;

  const normalizedRightPriceScaleWidth = Number.isFinite(rightPriceScaleWidth) && rightPriceScaleWidth > 0
    ? rightPriceScaleWidth
    : RIGHT_PRICE_SCALE_WIDTH;
  const base = !Number.isFinite(klineHostWidth) || klineHostWidth <= normalizedRightPriceScaleWidth
    ? DEFAULT_VISIBLE_BARS
    : clamp(
        Math.round(
          (resolveDetailChartPlotWidth(klineHostWidth, normalizedRightPriceScaleWidth) / TARGET_PIXELS_PER_BAR)
            / ZOOM_STEP_BARS,
        ) * ZOOM_STEP_BARS,
        MIN_ADAPTIVE_DEFAULT_BARS,
        MAX_ADAPTIVE_DEFAULT_BARS,
      );

  return Math.min(base, Math.floor(pointCount));
}

export function resolveInitialRange(
  pointCount: number,
  visibleCount: number,
): DetailChartLogicalRange | null {
  if (!Number.isFinite(pointCount) || pointCount <= 0) return null;
  if (!Number.isFinite(visibleCount) || visibleCount <= 0) return null;

  const count = Math.min(Math.floor(pointCount), Math.floor(visibleCount));
  const to = Math.floor(pointCount) - 1;
  return { from: to - (count - 1), to };
}

export function resolveVisibleCount(
  range: DetailChartLogicalRange | null,
  pointCount: number,
): number {
  if (!range || !Number.isFinite(pointCount) || pointCount <= 0) return 0;
  return clamp(Math.round(range.to - range.from) + 1, 1, Math.floor(pointCount));
}

export function resolveZoomAvailability(
  visibleCount: number,
  pointCount: number,
): DetailChartZoomAvailability {
  if (!Number.isFinite(pointCount) || pointCount < MIN_VISIBLE_BARS) {
    return { canZoomIn: false, canZoomOut: false };
  }

  const normalizedPointCount = Math.floor(pointCount);
  const effectiveMin = Math.min(MIN_VISIBLE_BARS, normalizedPointCount);
  const effectiveMax = Math.min(MAX_VISIBLE_BARS, normalizedPointCount);
  return {
    canZoomIn: visibleCount > effectiveMin,
    canZoomOut: visibleCount < effectiveMax,
  };
}

export function resolveZoomTargetCount(
  direction: "in" | "out",
  visibleCount: number,
  pointCount: number,
): number {
  if (!Number.isFinite(pointCount) || pointCount <= 0) return 0;
  const normalizedPointCount = Math.floor(pointCount);
  const normalizedVisibleCount = clamp(
    Math.round(visibleCount),
    1,
    normalizedPointCount,
  );

  return direction === "in"
    ? Math.max(Math.min(MIN_VISIBLE_BARS, normalizedPointCount), normalizedVisibleCount - ZOOM_STEP_BARS)
    : Math.min(MAX_VISIBLE_BARS, normalizedPointCount, normalizedVisibleCount + ZOOM_STEP_BARS);
}

export function resolveZoomedRange(
  currentRange: DetailChartLogicalRange,
  targetCount: number,
  pointCount: number,
): DetailChartLogicalRange {
  const normalizedPointCount = Math.max(0, Math.floor(pointCount));
  if (normalizedPointCount === 0) return { from: 0, to: 0 };

  const normalizedTargetCount = clamp(
    Math.floor(targetCount),
    1,
    normalizedPointCount,
  );
  const span = normalizedTargetCount - 1;
  const latestTo = normalizedPointCount - 1;

  if (isLatestRange(currentRange, normalizedPointCount)) {
    return { from: latestTo - span, to: latestTo };
  }

  const center = (currentRange.from + currentRange.to) / 2;
  return clampRangeAroundCenter(center, span, latestTo);
}

export function resolveRangeAfterPointCountChange(
  currentRange: DetailChartLogicalRange,
  previousPointCount: number,
  nextPointCount: number,
): DetailChartLogicalRange | null {
  if (!Number.isFinite(nextPointCount) || nextPointCount <= 0) return null;

  const normalizedNextPointCount = Math.floor(nextPointCount);
  const visibleCount = Math.min(
    resolveVisibleCount(currentRange, Math.max(1, Math.floor(previousPointCount))),
    normalizedNextPointCount,
  );
  if (visibleCount <= 0) return resolveInitialRange(normalizedNextPointCount, DEFAULT_VISIBLE_BARS);

  if (isLatestRange(currentRange, previousPointCount)) {
    return resolveInitialRange(normalizedNextPointCount, visibleCount);
  }

  const center = (currentRange.from + currentRange.to) / 2;
  return clampRangeAroundCenter(
    center,
    visibleCount - 1,
    normalizedNextPointCount - 1,
  );
}

function isLatestRange(range: DetailChartLogicalRange, pointCount: number): boolean {
  if (!Number.isFinite(pointCount) || pointCount <= 0) return false;
  return Math.abs(range.to - (Math.floor(pointCount) - 1)) <= LATEST_RANGE_TOLERANCE;
}

function clampRangeAroundCenter(
  center: number,
  span: number,
  latestTo: number,
): DetailChartLogicalRange {
  let from = center - span / 2;
  let to = center + span / 2;

  if (from < 0) {
    to -= from;
    from = 0;
  }
  if (to > latestTo) {
    from -= to - latestTo;
    to = latestTo;
  }
  if (from < 0) from = 0;

  return { from, to };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
