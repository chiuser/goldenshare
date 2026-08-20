import { describe, expect, it } from "vitest";

import {
  KDJ_RANGE_FIELDS,
  MACD_RANGE_FIELDS,
  resolveVisibleIndicatorRange,
} from "./detailChartIndicatorRange";
import type { DetailChartPoint } from "./detailChartTypes";

describe("resolveVisibleIndicatorRange", () => {
  it("uses only fully visible points and all three MACD fields", () => {
    const points = makePoints(4);
    points[0]!.macd = -99;
    points[1]!.dif = -4;
    points[2]!.dea = 8;
    points[3]!.macd = 99;

    expect(resolveVisibleIndicatorRange(points, { from: 0.2, to: 2.8 }, MACD_RANGE_FIELDS)).toEqual({
      dataMax: 8,
      dataMin: -4,
      domainMax: 8,
      domainMin: -4,
      isDegenerate: false,
    });
  });

  it("uses all KDJ fields without clamping J to 0 through 100", () => {
    const points = makePoints(2);
    points[0]!.k = 18;
    points[0]!.d = 25;
    points[0]!.j = -12;
    points[1]!.k = 91;
    points[1]!.d = 88;
    points[1]!.j = 132;

    expect(resolveVisibleIndicatorRange(points, { from: 0, to: 1 }, KDJ_RANGE_FIELDS)).toMatchObject({
      dataMax: 132,
      dataMin: -12,
      domainMax: 132,
      domainMin: -12,
    });
  });

  it("ignores null and non-finite values", () => {
    const points = makePoints(2);
    points[0]!.macd = null;
    points[0]!.dif = Number.NaN;
    points[0]!.dea = Number.POSITIVE_INFINITY;
    points[1]!.macd = -3;
    points[1]!.dif = 2;
    points[1]!.dea = null;

    expect(resolveVisibleIndicatorRange(points, { from: 0, to: 1 }, MACD_RANGE_FIELDS)).toMatchObject({
      dataMax: 2,
      dataMin: -3,
    });
  });

  it("returns null when the range contains no finite values", () => {
    const points = makePoints(1);
    points[0]!.macd = null;
    points[0]!.dif = Number.NaN;
    points[0]!.dea = Number.NEGATIVE_INFINITY;

    expect(resolveVisibleIndicatorRange(points, { from: 0, to: 0 }, MACD_RANGE_FIELDS)).toBeNull();
    expect(resolveVisibleIndicatorRange(points, null, MACD_RANGE_FIELDS)).toBeNull();
  });

  it.each([
    { expected: [-0.01, 0.01], value: 0 },
    { expected: [99, 101], value: 100 },
  ])("adds the frozen safety span for a degenerate value $value", ({ expected, value }) => {
    const points = makePoints(1);
    points[0]!.macd = value;
    points[0]!.dif = value;
    points[0]!.dea = value;

    expect(resolveVisibleIndicatorRange(points, { from: 0, to: 0 }, MACD_RANGE_FIELDS)).toEqual({
      dataMax: value,
      dataMin: value,
      domainMax: expected[1],
      domainMin: expected[0],
      isDegenerate: true,
    });
  });

  it.each([
    { expectedMax: 9, expectedMin: 2, values: [2, 5, 9] },
    { expectedMax: -2, expectedMin: -9, values: [-9, -5, -2] },
    { expectedMax: 7, expectedMin: -6, values: [-6, 0, 7] },
  ])("preserves one-sided and cross-zero domains", ({ expectedMax, expectedMin, values }) => {
    const points = makePoints(1);
    [points[0]!.macd, points[0]!.dif, points[0]!.dea] = values;

    expect(resolveVisibleIndicatorRange(points, { from: 0, to: 0 }, MACD_RANGE_FIELDS)).toMatchObject({
      dataMax: expectedMax,
      dataMin: expectedMin,
      domainMax: expectedMax,
      domainMin: expectedMin,
    });
  });
});

function makePoints(count: number): DetailChartPoint[] {
  return Array.from({ length: count }, (_, index) => ({
    time: `2026-01-${String(index + 1).padStart(2, "0")}`,
    fullDate: `2026-01-${String(index + 1).padStart(2, "0")}`,
    open: 10,
    high: 11,
    low: 9,
    close: 10,
    preClose: 10,
    changePct: 0,
    amplitude: 0,
    volume: 100,
    volumeDisplay: null,
    amount: 1000,
    turnoverRate: 1,
    macd: 0,
    dif: 0,
    dea: 0,
    k: 0,
    d: 0,
    j: 0,
    overlays: {},
  }));
}
