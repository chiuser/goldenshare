import { describe, expect, it } from "vitest";

import { buildHistorySegments, buildPaddedDomain, buildScatterGeometry, mapValue } from "./sectorPriceVolumeGeometry";

describe("sectorPriceVolumeGeometry", () => {
  it("keeps both scatter domains anchored to zero and pads equal values", () => {
    expect(buildPaddedDomain([5, 5], true)).toEqual({ min: -0.4, max: 5.4 });
    const geometry = buildScatterGeometry([
      row("BK1001.DC", 8, 30), row("BK1002.DC", -2, -10), row("BK1003.DC", null, 5),
    ]);
    expect(geometry.points).toHaveLength(2);
    expect(geometry.xDomain.min).toBeLessThan(0);
    expect(geometry.xDomain.max).toBeGreaterThan(0);
    expect(geometry.yDomain.min).toBeLessThan(0);
    expect(geometry.yDomain.max).toBeGreaterThan(0);
    expect(geometry.zeroX).toBeGreaterThan(geometry.left);
    expect(geometry.zeroY).toBeLessThan(geometry.bottom);
  });

  it("breaks history lines at null slots instead of filling them", () => {
    const geometry = buildHistorySegments([
      history("2026-08-25", 1), history("2026-08-26", null), history("2026-08-27", 3),
    ], "priceMomentumPct");
    expect(geometry.mapped[1]).toBeNull();
    expect(geometry.segments).toHaveLength(2);
    expect(geometry.segments[0]).toHaveLength(1);
    expect(geometry.segments[1]).toHaveLength(1);
    expect(mapValue(0, { min: -1, max: 1 }, 10, 30)).toBe(20);
  });
});

function row(sectorCode: string, priceMomentumPct: number | null, amountActivityPct: number | null) {
  return { sectorCode, sectorName: sectorCode, industryLevel: 1 as const, hierarchyPath: sectorCode, parentSectorCode: null, parentSectorName: null, rootSectorCode: sectorCode, rootSectorName: sectorCode, priceMomentumPct, amountActivityPct, priceRank: priceMomentumPct === null ? null : 1, priceRankableCount: 2, amountRank: amountActivityPct === null ? null : 1, amountRankableCount: 2, state: priceMomentumPct === null || amountActivityPct === null ? null : "JOINT" as const, priceMissingReason: priceMomentumPct === null ? "DATE_MISSING" as const : null, amountMissingReason: amountActivityPct === null ? "DATE_MISSING" as const : null, priceText: "", amountText: "", stateText: "", stateClass: "", canDrillDown: true };
}
function history(tradeDate: string, priceMomentumPct: number | null) { return { tradeDate, priceMomentumPct, amountActivityPct: 1, priceMissingReason: priceMomentumPct === null ? "DATE_MISSING" as const : null, amountMissingReason: null }; }
