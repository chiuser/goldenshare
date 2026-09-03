import { describe, expect, it } from "vitest";

import { buildSectorRelativeRotationMetaViewModel, buildSectorRelativeRotationResultsViewModel, SectorRelativeRotationContractError } from "./sectorRelativeRotationAdapter";
import { relativeMetaPayload, relativeResultsPayload } from "./sectorRelativeRotationTestFixtures";
import type { SectorRelativeRotationResultsRequest } from "../model/sectorRelativeRotationTypes";

const request: SectorRelativeRotationResultsRequest = { market: "CN_A", tradeDate: "2026-08-27", scope: "LEVEL_1", period: 20, trailLength: 20, hierarchyVersion: "dc-industry-v1" };

describe("sectorRelativeRotationAdapter", () => {
  it.each([false, true])("retains published partial facts and the observed trail date (delayed=%s)", (delayed) => {
    const meta: any = relativeMetaPayload();
    const results: any = relativeResultsPayload();
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
    if (delayed) {
      results.analysis.selectedTrail.points[0].tradeDate = "2026-08-25";
      results.analysis.selectedTrail.points[1].tradeDate = "2026-08-26";
    }
    expect(buildSectorRelativeRotationMetaViewModel(meta).tradingDay.observedAvailability).toBe("PARTIAL");
    const view = buildSectorRelativeRotationResultsViewModel(results, request);
    expect(view.kind).toBe("ready");
    if (view.kind !== "ready") return;
    expect(view.data.analysis.items).toHaveLength(4);
    expect(view.data.analysis.items[3]?.percentileText).toBe("--");
    expect(view.data.analysis.selectedTrail.points.at(-1)?.tradeDate).toBe(results.tradingDay.observedTradeDate);
  });

  it("keeps an unpublished historical date as a null slot without dropping it", () => {
    const payload: any = relativeResultsPayload();
    Object.assign(payload.analysis.selectedTrail.points[0], {
      returnPct: null, percentile: null, percentileDelta5d: null,
      coordinateStatus: "UNAVAILABLE", rotationStatus: "DATA_INSUFFICIENT",
      currentMissingReason: "DATE_MISSING", comparisonMissingReason: "DATE_MISSING",
    });
    const view = buildSectorRelativeRotationResultsViewModel(payload, request);
    expect(view.kind).toBe("ready");
    if (view.kind !== "ready") return;
    expect(view.data.analysis.selectedTrail.points).toHaveLength(2);
    expect(view.data.analysis.selectedTrail.points[0]?.percentile).toBeNull();
  });

  it("accepts the exact frozen Meta and derives only display partitions", () => {
    const meta = buildSectorRelativeRotationMetaViewModel(relativeMetaPayload());
    expect(meta.formula.periods).toEqual([5, 10, 20, 30]);
    expect(meta.formula.trailLengths).toEqual([20, 30, 60]);
    expect(meta.level1Nodes).toHaveLength(4);
  });

  it("accepts canonical Results without changing rows or null slots", () => {
    const result = buildSectorRelativeRotationResultsViewModel(relativeResultsPayload(), request);
    expect(result.kind).toBe("ready");
    if (result.kind !== "ready") return;
    expect(result.data.analysis.items.map((row) => row.sectorCode)).toEqual(["BK1001.DC", "BK1002.DC", "BK1003.DC", "BK1004.DC"]);
    expect(result.data.analysis.items[3]?.percentileText).toBe("--");
    expect(result.data.analysis.selectedTrail.points).toHaveLength(2);
  });

  it.each([
    (payload: any) => { payload.extra = true; },
    (payload: any) => { payload.analysis.items[0].rotationStatus = "WEAK_NOT_IMPROVING"; },
    (payload: any) => { payload.analysis.plottableCount = 2; },
    (payload: any) => { payload.analysis.items.reverse(); },
    (payload: any) => { payload.analysis.selectedTrail.dateSlotCount = 1; },
    (payload: any) => { payload.analysis.selectedTrail.points[1].tradeDate = "2026-08-26"; },
  ])("rejects contract tampering", (mutate) => {
    const payload = relativeResultsPayload();
    mutate(payload);
    expect(() => buildSectorRelativeRotationResultsViewModel(payload, request)).toThrow(SectorRelativeRotationContractError);
  });

  it("rejects a response from another request fact set", () => {
    expect(() => buildSectorRelativeRotationResultsViewModel(relativeResultsPayload(), { ...request, period: 10 })).toThrow("响应事实与请求不一致");
  });
});
