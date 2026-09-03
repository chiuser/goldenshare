import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import {
  buildSectorDualMomentumMetaViewModel,
  buildSectorDualMomentumResultsViewModel,
} from "./sectorDualMomentumAdapter";
import type { SectorDualMomentumResultsRequest } from "../model/sectorDualMomentumTypes";

const request: SectorDualMomentumResultsRequest = {
  market: "CN_A",
  tradeDate: "2026-08-27",
  scope: "LEVEL_1",
  period: 20,
  leadingThreshold: 80,
  hierarchyVersion: "dc-industry-v1",
};

describe("sectorDualMomentumAdapter", () => {
  it.each([false, true])("accepts published partial dates without hiding the available analysis (delayed=%s)", (delayed) => {
    const meta: any = metaPayload();
    const results: any = resultsPayload();
    for (const payload of [meta, results]) {
      payload.status = delayed ? "DELAYED" : "READY";
      payload.pageStatus.status = payload.status;
      payload.exceptionCode = delayed ? "SA_SOURCE_DELAYED" : null;
      payload.tradingDay.expectedAvailability = delayed ? "MISSING" : "PARTIAL";
      payload.tradingDay.expectedValidSectorCount = delayed ? 0 : 3;
      payload.tradingDay.observedTradeDate = delayed ? "2026-08-26" : "2026-08-27";
      payload.tradingDay.observedAvailability = "PARTIAL";
      payload.tradingDay.observedValidSectorCount = 3;
    }
    meta.tradeDates[1].availability = meta.tradingDay.expectedAvailability;
    meta.tradeDates[1].validSectorCount = meta.tradingDay.expectedValidSectorCount;
    expect(buildSectorDualMomentumMetaViewModel(meta).tradingDay.observedAvailability).toBe("PARTIAL");
    const view = buildSectorDualMomentumResultsViewModel(results, request);
    expect(view.kind).toBe("ready");
    if (view.kind !== "ready") return;
    expect(view.data.analysis.items).toHaveLength(4);
    expect(view.data.analysis.items[3].returnText).toBe("--");
  });

  it("strictly adapts frozen Meta and Results facts", () => {
    const meta = buildSectorDualMomentumMetaViewModel(metaPayload());
    const results = buildSectorDualMomentumResultsViewModel(resultsPayload(), request);
    expect(meta.formula.periods).toEqual([5, 10, 20, 30]);
    expect(meta.level1Nodes).toHaveLength(4);
    expect(results.kind).toBe("ready");
    if (results.kind !== "ready") return;
    expect(results.data.analysis.items.map((row) => row.statusText)).toEqual([
      "符合双动量", "领先未上涨", "上涨未领先", "数据不足",
    ]);
    expect(results.data.analysis.items[3]).toMatchObject({ returnText: "--", percentileText: "--" });
  });

  it.each([
    (payload: any) => { payload.extra = true; },
    (payload: any) => { payload.formula.periods = [10, 5, 20, 30]; },
    (payload: any) => { payload.formula.formulaVersion = 2; },
    (payload: any) => { payload.tradeDates[0].availability = "UNKNOWN"; },
    (payload: any) => { payload.hierarchy.nodes[0].extra = "leak"; },
  ])("rejects invalid Meta contracts", (mutate) => {
    const payload = structuredClone(metaPayload());
    mutate(payload);
    expect(() => buildSectorDualMomentumMetaViewModel(payload)).toThrow();
  });

  it.each([
    (payload: any) => { payload.extra = true; },
    (payload: any) => { payload.analysis.formulaKey = "other"; },
    (payload: any) => { payload.analysis.items[1].sectorCode = payload.analysis.items[0].sectorCode; },
    (payload: any) => { payload.analysis.totalCount = 99; },
    (payload: any) => { payload.analysis.items.reverse(); },
    (payload: any) => { payload.analysis.items[0].qualificationStatus = "NOT_QUALIFIED"; },
    (payload: any) => { payload.analysis.items[3].returnPct = 0; },
    (payload: any) => { payload.status = "EMPTY"; payload.pageStatus.status = "EMPTY"; payload.exceptionCode = "SA_SOURCE_EMPTY"; },
  ])("rejects invalid Results contracts", (mutate) => {
    const payload = structuredClone(resultsPayload());
    mutate(payload);
    expect(() => buildSectorDualMomentumResultsViewModel(payload, request)).toThrow();
  });

  it("rejects request fact mismatches", () => {
    expect(() => buildSectorDualMomentumResultsViewModel(resultsPayload(), { ...request, period: 10 })).toThrow(/周期或阈值/);
    expect(() => buildSectorDualMomentumResultsViewModel(resultsPayload(), { ...request, hierarchyVersion: "stale" })).toThrow(/层级版本/);
  });

  it("keeps Empty and Error outside the Ready analysis contract", () => {
    const empty: any = resultsPayload();
    empty.status = "EMPTY";
    empty.pageStatus.status = "EMPTY";
    empty.analysis = null;
    empty.message = "暂无数据";
    empty.exceptionCode = "SA_SOURCE_EMPTY";
    expect(buildSectorDualMomentumResultsViewModel(empty, request)).toEqual({ kind: "empty", message: "暂无数据" });

    const error = structuredClone(empty);
    error.status = "ERROR";
    error.pageStatus.status = "ERROR";
    error.message = "读取失败";
    error.exceptionCode = "SA_QUERY_FAILED";
    expect(buildSectorDualMomentumResultsViewModel(error, request)).toEqual({ kind: "error", message: "读取失败", retryable: true });
  });

  it("contains no frontend qualification formula", () => {
    const directory = `${process.cwd()}/src/features/wealth-exploration/sector-analysis/dual-momentum`;
    const adapterSource = readFileSync(`${directory}/api/sectorDualMomentumAdapter.ts`, "utf8");
    const controllerSource = readFileSync(`${directory}/model/useSectorDualMomentumController.ts`, "utf8");
    expect(`${adapterSource}\n${controllerSource}`).not.toMatch(/percentile\s*>=\s*(?:threshold|leadingThreshold)/);
    expect(`${adapterSource}\n${controllerSource}`).not.toMatch(/returnPct\s*>\s*0[^?\n]*QUALIFIED/);
  });
});

export function metaPayload() {
  return {
    status: "READY",
    tradingDay: tradingDayPayload(),
    pageStatus: pageStatusPayload(),
    message: null,
    exceptionCode: null,
    debugInfo: null,
    formula: {
      formulaKey: "sector-dual-momentum",
      formulaVersion: 1,
      basisFormulaKey: "sector-cross-sectional-momentum",
      basisFormulaVersion: 1,
      periods: [5, 10, 20, 30],
      leadingThresholds: [70, 80, 90],
      minimumGroupSize: 3,
      scopes: ["LEVEL_1", "LEVEL_2", "LEVEL_3", "LEVEL_1_CHILDREN", "LEVEL_2_CHILDREN"],
    },
    defaults: { scope: "LEVEL_1", period: 20, leadingThreshold: 80, resultView: "QUALIFIED" },
    hierarchy: {
      hierarchyVersion: "dc-industry-v1",
      publishedAt: "2026-08-27T20:30:00+08:00",
      nodes: hierarchyNodes(),
    },
    coverageStartDate: "2026-08-26",
    coverageEndDate: "2026-08-27",
    tradeDates: [
      { tradeDate: "2026-08-26", availability: "PARTIAL", expectedSectorCount: 4, validSectorCount: 3 },
      { tradeDate: "2026-08-27", availability: "COMPLETE", expectedSectorCount: 4, validSectorCount: 4 },
    ],
  };
}

export function resultsPayload() {
  return {
    status: "READY",
    tradingDay: tradingDayPayload(),
    pageStatus: pageStatusPayload(),
    analysis: {
      formulaKey: "sector-dual-momentum",
      formulaVersion: 1,
      basisFormulaKey: "sector-cross-sectional-momentum",
      basisFormulaVersion: 1,
      hierarchyVersion: "dc-industry-v1",
      scope: "LEVEL_1",
      period: 20,
      leadingThreshold: 80,
      minimumGroupSize: 3,
      parentSelection: { level1Code: null, level1Name: null, level2Code: null, level2Name: null },
      totalCount: 4,
      calculableCount: 3,
      qualifiedCount: 1,
      insufficientCount: 1,
      plottableCount: 3,
      items: [
        row("BK1001.DC", "电子", 3.97, 1, 100, "POSITIVE", "LEADING", "QUALIFIED", "QUALIFIED"),
        row("BK1003.DC", "煤炭", -0.5, 2, 80, "NOT_POSITIVE", "LEADING", "NOT_QUALIFIED", "NOT_UP_LEADING"),
        row("BK1002.DC", "通信", 1.2, 3, 66.7, "POSITIVE", "NOT_LEADING", "NOT_QUALIFIED", "UP_NOT_LEADING"),
        {
          sectorCode: "BK1004.DC", sectorName: "房地产", industryLevel: 1,
          parentSectorCode: null, parentSectorName: null, hierarchyPath: "房地产", canDrillDown: true,
          returnPct: null, strengthRank: null, percentile: null, absoluteStatus: "UNAVAILABLE",
          relativeStatus: "UNAVAILABLE", qualificationStatus: "NOT_EVALUATED", coordinateStatus: "UNAVAILABLE",
          displayStatus: "DATA_INSUFFICIENT", missingReason: "HISTORY_INSUFFICIENT",
        },
      ],
    },
    message: null,
    exceptionCode: null,
    debugInfo: null,
  };
}

function row(code: string, name: string, returnPct: number, rank: number, percentile: number, absoluteStatus: string, relativeStatus: string, qualificationStatus: string, displayStatus: string) {
  return {
    sectorCode: code, sectorName: name, industryLevel: 1, parentSectorCode: null, parentSectorName: null,
    hierarchyPath: name, canDrillDown: true, returnPct, strengthRank: rank, percentile, absoluteStatus,
    relativeStatus, qualificationStatus, coordinateStatus: "PLOTTABLE", displayStatus, missingReason: null,
  };
}

function hierarchyNodes() {
  return ["电子", "通信", "煤炭", "房地产"].map((sectorName, index) => ({
    sectorCode: `BK100${index + 1}.DC`, sectorName, industryLevel: 1, parentSectorCode: null,
    parentSectorName: null, rootSectorCode: `BK100${index + 1}.DC`, rootSectorName: sectorName,
    hierarchyPath: sectorName, displayOrder: index + 1, isLeaf: false,
  }));
}

function tradingDayPayload() {
  return {
    expectedTradeDate: "2026-08-27", observedTradeDate: "2026-08-27", expectedAvailability: "COMPLETE",
    expectedSectorCount: 4, expectedValidSectorCount: 4, observedAvailability: "COMPLETE", observedValidSectorCount: 4,
  };
}

function pageStatusPayload() {
  return { status: "READY", displayText: "2026-08-27 盘后数据", asOfTime: "2026-08-27T20:31:00+08:00" };
}
