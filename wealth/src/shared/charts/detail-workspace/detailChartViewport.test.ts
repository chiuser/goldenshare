import { describe, expect, it } from "vitest";

import {
  DEFAULT_VISIBLE_BARS,
  MAX_VISIBLE_BARS,
  MIN_VISIBLE_BARS,
  resolveAdaptiveVisibleCount,
  resolveDetailChartPlotWidth,
  resolveInitialRange,
  resolveRangeAfterPointCountChange,
  resolveSharedRightPriceScaleWidth,
  resolveVisibleCount,
  resolveZoomAvailability,
  resolveZoomedRange,
  resolveZoomTargetCount,
} from "./detailChartViewport";

describe("detailChartViewport", () => {
  it("uses the widest measured right price scale with the configured minimum", () => {
    expect(resolveSharedRightPriceScaleWidth([56, 72, 88, 64])).toBe(88);
    expect(resolveSharedRightPriceScaleWidth([72.1, 72, 64, 0])).toBe(73);
    expect(resolveSharedRightPriceScaleWidth([40, 48], 64)).toBe(64);
  });

  it("ignores invalid price scale widths and falls back to the approved minimum", () => {
    expect(resolveSharedRightPriceScaleWidth([])).toBe(56);
    expect(resolveSharedRightPriceScaleWidth([0, -1, Number.NaN, Number.POSITIVE_INFINITY])).toBe(56);
    expect(resolveSharedRightPriceScaleWidth([80], Number.NaN)).toBe(80);
  });

  it("resolves the drawable plot width without allowing zero or invalid divisors", () => {
    expect(resolveDetailChartPlotWidth(1000, 88)).toBe(912);
    expect(resolveDetailChartPlotWidth(1000, Number.NaN)).toBe(944);
    expect(resolveDetailChartPlotWidth(56, 56)).toBe(1);
    expect(resolveDetailChartPlotWidth(40, 56)).toBe(1);
    expect(resolveDetailChartPlotWidth(Number.NaN, 56)).toBe(1);
  });

  it("resolves 120 bars for the approved 1600px chart width", () => {
    expect(resolveAdaptiveVisibleCount(1193, 300)).toBe(120);
  });

  it("uses the shared actual right scale width for adaptive density", () => {
    expect(resolveAdaptiveVisibleCount(1193, 300, 56)).toBe(120);
    expect(resolveAdaptiveVisibleCount(1193, 300, 180)).toBe(105);
  });

  it("clamps adaptive defaults to 75 on narrow hosts and 150 on wide hosts", () => {
    expect(resolveAdaptiveVisibleCount(600, 300)).toBe(75);
    expect(resolveAdaptiveVisibleCount(2000, 300)).toBe(150);
  });

  it.each([0, Number.NaN, Number.POSITIVE_INFINITY, 56, -1])(
    "falls back to 120 bars for invalid host width %s",
    (width) => {
      expect(resolveAdaptiveVisibleCount(width, 300)).toBe(DEFAULT_VISIBLE_BARS);
    },
  );

  it("keeps the 120-bar fallback when the host cannot contain the shared right scale", () => {
    expect(resolveAdaptiveVisibleCount(100, 300, 120)).toBe(DEFAULT_VISIBLE_BARS);
    expect(resolveAdaptiveVisibleCount(1193, 300, Number.NaN)).toBe(120);
  });

  it.each([
    [0, 0],
    [30, 30],
    [44, 44],
    [45, 45],
    [60, 60],
    [100, 100],
    [180, 120],
    [300, 120],
    [500, 120],
  ])("caps the adaptive default for pointCount=%i", (pointCount, expected) => {
    expect(resolveAdaptiveVisibleCount(1193, pointCount)).toBe(expected);
  });

  it("always anchors a non-empty initial range to the latest point", () => {
    expect(resolveInitialRange(300, 120)).toEqual({ from: 180, to: 299 });
    expect(resolveInitialRange(30, 120)).toEqual({ from: 0, to: 29 });
    expect(resolveInitialRange(0, 120)).toBeNull();
    expect(resolveInitialRange(300, 0)).toBeNull();
  });

  it("reaches the frozen 45 and 180 limits in 15-bar steps", () => {
    let count = 120;
    while (resolveZoomAvailability(count, 300).canZoomIn) {
      count = resolveZoomTargetCount("in", count, 300);
    }
    expect(count).toBe(MIN_VISIBLE_BARS);

    while (resolveZoomAvailability(count, 300).canZoomOut) {
      count = resolveZoomTargetCount("out", count, 300);
    }
    expect(count).toBe(MAX_VISIBLE_BARS);
  });

  it("lands on a non-step real upper bound and disables short data", () => {
    expect(resolveZoomTargetCount("out", 165, 173)).toBe(173);
    expect(resolveZoomAvailability(44, 44)).toEqual({ canZoomIn: false, canZoomOut: false });
    expect(resolveZoomAvailability(45, 45)).toEqual({ canZoomIn: false, canZoomOut: false });
  });

  it("keeps the latest right edge fixed while zooming", () => {
    expect(resolveZoomedRange({ from: 180, to: 299 }, 105, 300)).toEqual({ from: 195, to: 299 });
    expect(resolveZoomedRange({ from: 180.25, to: 298.6 }, 135, 300)).toEqual({ from: 165, to: 299 });
  });

  it("keeps the historical center while zooming", () => {
    expect(resolveZoomedRange({ from: 60, to: 179 }, 90, 300)).toEqual({ from: 75, to: 164 });
  });

  it("translates historical ranges at both edges without shrinking the target span", () => {
    expect(resolveZoomedRange({ from: 0, to: 44 }, 90, 300)).toEqual({ from: 0, to: 89 });
    expect(resolveZoomedRange({ from: 250, to: 294 }, 90, 300)).toEqual({ from: 210, to: 299 });
    expect(resolveVisibleCount(resolveZoomedRange({ from: 250, to: 294 }, 90, 300), 300)).toBe(90);
  });

  it("follows appended bars only when the previous range was at the latest edge", () => {
    expect(resolveRangeAfterPointCountChange({ from: 180, to: 299 }, 300, 301)).toEqual({ from: 181, to: 300 });
    expect(resolveRangeAfterPointCountChange({ from: 60, to: 179 }, 300, 301)).toEqual({ from: 60, to: 179 });
  });

  it("clamps safely when the point set shrinks", () => {
    expect(resolveRangeAfterPointCountChange({ from: 180, to: 299 }, 300, 80)).toEqual({ from: 0, to: 79 });
    const historical = resolveRangeAfterPointCountChange({ from: 100, to: 219 }, 300, 150);
    expect(historical).toEqual({ from: 30, to: 149 });
    expect(resolveRangeAfterPointCountChange({ from: 0, to: 44 }, 45, 0)).toBeNull();
  });
});
