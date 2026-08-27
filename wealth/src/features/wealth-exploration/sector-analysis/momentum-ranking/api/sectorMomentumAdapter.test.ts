import { describe, expect, it } from "vitest";

import {
  buildSectorMomentumHistoryViewModel,
  buildSectorMomentumMetaViewModel,
  buildSectorMomentumRankingViewModel,
} from "./sectorMomentumAdapter";

describe("sectorMomentumAdapter", () => {
  it("keeps backend order and null rows while only adding display text", () => {
    const result = buildSectorMomentumRankingViewModel(rankingPayload());
    expect(result.status).toBe("READY");
    if (result.status !== "READY" && result.status !== "DELAYED") return;
    expect(result.rows.map((row) => row.sectorCode)).toEqual(["BK1002.DC", "BK1001.DC"]);
    expect(result.rows[0]).toMatchObject({ returnText: "--", returnBarWidthPct: 0, percentileText: "--", strengthRankText: "--" });
    expect(result.rows[1]).toMatchObject({ returnText: "+2.35%", returnBarWidthPct: 50, percentileText: "100.0%", strengthRankText: "1" });
  });

  it("keeps all meta trade dates including PARTIAL and MISSING", () => {
    const result = buildSectorMomentumMetaViewModel(metaPayload());
    expect(result.tradeDates.map((item) => item.availability)).toEqual(["COMPLETE", "PARTIAL", "MISSING"]);
    expect(result.level1Nodes).toHaveLength(1);
    expect(result.level2Nodes).toHaveLength(1);
    expect(result.level3Nodes).toHaveLength(1);
  });

  it("zips aligned history without filling nulls", () => {
    const result = buildSectorMomentumHistoryViewModel(historyPayload());
    expect(result.status).toBe("READY");
    if (result.status !== "READY" && result.status !== "DELAYED") return;
    expect(result.points).toEqual([
      { tradeDate: "2026-08-20", returnPct: null, strengthRank: null, calculableCount: 1, totalCount: 2, percentile: null },
      { tradeDate: "2026-08-21", returnPct: 2.35, strengthRank: 1, calculableCount: 2, totalCount: 2, percentile: 100 },
    ]);
  });

  it("rejects mismatched history dates instead of joining different facts", () => {
    const payload = historyPayload();
    payload.historicalRanks[1]!.tradeDate = "2026-08-19";
    expect(() => buildSectorMomentumHistoryViewModel(payload)).toThrow("两条历史序列日期不一致");
  });
});

function metaPayload() {
  const nodes = [
    node("BK1001.DC", "一级甲", 1, null, "BK1001.DC", "一级甲"),
    node("BK1101.DC", "二级甲", 2, "BK1001.DC", "BK1001.DC", "一级甲/二级甲"),
    node("BK1201.DC", "三级甲", 3, "BK1101.DC", "BK1001.DC", "一级甲/二级甲/三级甲"),
  ];
  return {
    formula: { formulaKey: "sector-cross-sectional-momentum", formulaVersion: 1, periods: [1, 5, 10, 20, 30], historyRanges: [20, 30, 60], scopes: ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"], directions: ["GAINERS", "LOSERS"] },
    hierarchy: { hierarchyVersion: "v1", publishedAt: "2026-08-21T20:00:00+08:00", nodes },
    coverageStartDate: "2026-08-19",
    coverageEndDate: "2026-08-21",
    tradeDates: [
      { tradeDate: "2026-08-19", availability: "COMPLETE", expectedSectorCount: 3, validSectorCount: 3 },
      { tradeDate: "2026-08-20", availability: "PARTIAL", expectedSectorCount: 3, validSectorCount: 2 },
      { tradeDate: "2026-08-21", availability: "MISSING", expectedSectorCount: 3, validSectorCount: 0 },
    ],
  };
}

function node(code: string, name: string, level: number, parent: string | null, root: string, path: string) {
  return { sectorCode: code, sectorName: name, industryLevel: level, parentSectorCode: parent, parentSectorName: parent ? "父级" : null, rootSectorCode: root, rootSectorName: "一级甲", hierarchyPath: path, displayOrder: level, isLeaf: level === 3 };
}

function tradingDay() {
  return { expectedTradeDate: "2026-08-21", observedTradeDate: "2026-08-21", expectedAvailability: "COMPLETE", expectedSectorCount: 2, expectedValidSectorCount: 2, observedAvailability: "COMPLETE", observedValidSectorCount: 2 };
}

function pageStatus() {
  return { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-08-21T20:00:00+08:00" };
}

function rankingPayload() {
  return {
    status: "READY",
    tradingDay: tradingDay(),
    pageStatus: pageStatus(),
    ranking: {
      formulaKey: "sector-cross-sectional-momentum",
      formulaVersion: 1,
      hierarchyVersion: "v1",
      scope: "LEVEL_1",
      period: 1,
      direction: "LOSERS",
      parentSelection: { level1Code: null, level1Name: null, level2Code: null, level2Name: null },
      totalCount: 2,
      calculableCount: 1,
      rows: [
        { listPosition: 1, strengthRank: null, sectorCode: "BK1002.DC", sectorName: "一级乙", industryLevel: 1, parentSectorCode: null, parentSectorName: null, hierarchyPath: "一级乙", returnPct: null, percentile: null, canDrillDown: true },
        { listPosition: 2, strengthRank: 1, sectorCode: "BK1001.DC", sectorName: "一级甲", industryLevel: 1, parentSectorCode: null, parentSectorName: null, hierarchyPath: "一级甲", returnPct: 2.35, percentile: 100, canDrillDown: true },
      ],
    },
    message: null,
    exceptionCode: null,
  };
}

function historyPayload() {
  return {
    status: "READY",
    tradingDay: tradingDay(),
    pageStatus: pageStatus(),
    detail: {
      sectorCode: "BK1001.DC", sectorName: "一级甲", industryLevel: 1, hierarchyPath: "一级甲", scopeTitle: "一级行业总榜", returnPct: 2.35, percentile: 100,
      currentScopeStrengthRank: 1, currentScopeCalculableCount: 2, currentScopeTotalCount: 2,
      globalLevelStrengthRank: 1, globalLevelCalculableCount: 2, globalLevelTotalCount: 2,
      parentStrengthRank: null, parentCalculableCount: null, parentTotalCount: null,
      formulaKey: "sector-cross-sectional-momentum", formulaVersion: 1, hierarchyVersion: "v1",
    },
    rollingReturns: [{ tradeDate: "2026-08-20", returnPct: null }, { tradeDate: "2026-08-21", returnPct: 2.35 }],
    historicalRanks: [{ tradeDate: "2026-08-20", strengthRank: null, calculableCount: 1, totalCount: 2, percentile: null }, { tradeDate: "2026-08-21", strengthRank: 1, calculableCount: 2, totalCount: 2, percentile: 100 }],
    message: null,
    exceptionCode: null,
  };
}
