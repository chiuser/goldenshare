import { describe, expect, it } from "vitest";

import { buildRelativeRotationPlotScale, buildTrailSegments, niceCeil, toRelativeRotationPixels } from "./relativeRotationPlotGeometry";
import type { SectorRelativeRotationRowViewModel, SectorRelativeRotationTrailPointViewModel } from "./sectorRelativeRotationTypes";

describe("relativeRotationPlotGeometry", () => {
  it("uses a symmetric nice 1/2/5 scale across snapshot and trail", () => {
    const scale = buildRelativeRotationPlotScale([row(4.1)], [trailPoint(-7.6)]);
    expect(scale.yMin).toBe(-10);
    expect(scale.yMax).toBe(10);
    expect(scale.yTicks).toEqual([-10, -5, 0, 5, 10]);
    expect(Object.isFrozen(scale)).toBe(true);
    expect(toRelativeRotationPixels(50, 0, scale)).toEqual({ x: 560, y: 360.5 });
  });

  it("falls back to one and rounds upward with the frozen sequence", () => {
    expect(buildRelativeRotationPlotScale([], []).yMax).toBe(1);
    expect(niceCeil(1.01)).toBe(2);
    expect(niceCeil(2.01)).toBe(5);
    expect(niceCeil(5.01)).toBe(10);
  });

  it("breaks a trail at every null coordinate slot", () => {
    const scale = buildRelativeRotationPlotScale([row(2)], []);
    const missing = { ...trailPoint(null), coordinateStatus: "UNAVAILABLE" as const, percentile: null, returnPct: null, currentMissingReason: "DATE_MISSING" as const };
    const segments = buildTrailSegments([trailPoint(1), missing, trailPoint(2), trailPoint(3)], scale);
    expect(segments.map((segment) => segment.length)).toEqual([1, 2]);
  });
});

function row(delta: number): SectorRelativeRotationRowViewModel {
  return { sectorCode: "BK1001.DC", sectorName: "电子", industryLevel: 1, parentSectorCode: null, parentSectorName: null, hierarchyPath: "电子", canDrillDown: true, returnPct: 1, strengthRank: 1, percentile: 80, percentileDelta5d: delta, rotationStatus: "LEADING_IMPROVING", coordinateStatus: "PLOTTABLE", currentMissingReason: null, comparisonMissingReason: null, returnText: "+1.00%", percentileText: "80.0%", deltaText: "+1.0", statusText: "领先且改善", statusClass: "leading-improving", directionClass: "up" };
}
function trailPoint(delta: number | null): SectorRelativeRotationTrailPointViewModel {
  return { tradeDate: "2026-08-27", returnPct: 1, percentile: 80, percentileDelta5d: delta, rotationStatus: delta === null ? "DATA_INSUFFICIENT" : "LEADING_IMPROVING", coordinateStatus: delta === null ? "UNAVAILABLE" : "PLOTTABLE", currentMissingReason: null, comparisonMissingReason: delta === null ? "DATE_MISSING" : null };
}
