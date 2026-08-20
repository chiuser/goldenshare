import { describe, expect, it } from "vitest";

import {
  resolveVisibleExtrema,
  resolveVisibleIndexRange,
  type DetailChartVisibleCandle,
} from "./detailChartVisibleExtrema";

describe("detailChartVisibleExtrema", () => {
  it("rejects empty, non-finite, reversed, and out-of-bounds ranges", () => {
    expect(resolveVisibleIndexRange(null, 3)).toBeNull();
    expect(resolveVisibleIndexRange({ from: Number.NaN, to: 2 }, 3)).toBeNull();
    expect(resolveVisibleIndexRange({ from: 0, to: Number.POSITIVE_INFINITY }, 3)).toBeNull();
    expect(resolveVisibleIndexRange({ from: 2, to: 1 }, 3)).toBeNull();
    expect(resolveVisibleIndexRange({ from: 4, to: 5 }, 3)).toBeNull();
    expect(resolveVisibleIndexRange({ from: -5, to: -1 }, 3)).toBeNull();
    expect(resolveVisibleIndexRange({ from: 0, to: 2 }, 0)).toBeNull();
  });

  it("counts only complete logical indexes and clamps them to the point set", () => {
    expect(resolveVisibleIndexRange({ from: 0.25, to: 3.75 }, 5)).toEqual({
      endIndex: 3,
      startIndex: 1,
    });
    expect(resolveVisibleIndexRange({ from: -4.5, to: 20 }, 5)).toEqual({
      endIndex: 4,
      startIndex: 0,
    });
  });

  it("selects high and low independently from the visible range", () => {
    const points = [
      point("2026-08-10", 30, 20),
      point("2026-08-11", 50, 18),
      point("2026-08-12", 45, 10),
      point("2026-08-13", 60, 12),
    ];

    expect(resolveVisibleExtrema(points, { from: 0.1, to: 2.9 })).toEqual({
      high: { index: 1, time: "2026-08-11", value: 50 },
      low: { index: 2, time: "2026-08-12", value: 10 },
    });
  });

  it("chooses the latest logical index when extrema values are equal", () => {
    const points = [
      point("2026-08-10", 50, 10),
      point("2026-08-11", 40, 12),
      point("2026-08-12", 50, 10),
    ];

    expect(resolveVisibleExtrema(points, { from: 0, to: 2 })).toEqual({
      high: { index: 2, time: "2026-08-12", value: 50 },
      low: { index: 2, time: "2026-08-12", value: 10 },
    });
  });

  it("ignores null and non-finite prices without converting them to zero", () => {
    const points = [
      point("2026-08-10", null, null),
      point("2026-08-11", Number.NaN, Number.NEGATIVE_INFINITY),
      point("2026-08-12", 20, 8),
    ];

    expect(resolveVisibleExtrema(points, { from: 0, to: 1 })).toEqual({ high: null, low: null });
    expect(resolveVisibleExtrema(points, { from: 0, to: 2 })).toEqual({
      high: { index: 2, time: "2026-08-12", value: 20 },
      low: { index: 2, time: "2026-08-12", value: 8 },
    });
  });

  it("does not mutate or reorder the input points", () => {
    const points = [
      point("2026-08-11", 20, 8),
      point("2026-08-12", 30, 7),
    ];
    const snapshot = structuredClone(points);

    resolveVisibleExtrema(points, { from: 0, to: 1 });

    expect(points).toEqual(snapshot);
  });
});

function point(time: string, high: number | null, low: number | null): DetailChartVisibleCandle {
  return { high, low, time };
}
