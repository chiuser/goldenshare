import { describe, expect, it } from "vitest";

import { buildSectorRelativeRotationMetaViewModel, buildSectorRelativeRotationResultsViewModel, SectorRelativeRotationContractError } from "./sectorRelativeRotationAdapter";
import { relativeMetaPayload, relativeResultsPayload } from "./sectorRelativeRotationTestFixtures";
import type { SectorRelativeRotationResultsRequest } from "../model/sectorRelativeRotationTypes";

const request: SectorRelativeRotationResultsRequest = { market: "CN_A", tradeDate: "2026-08-27", scope: "LEVEL_1", period: 20, trailLength: 20, hierarchyVersion: "dc-industry-v1" };

describe("sectorRelativeRotationAdapter", () => {
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
