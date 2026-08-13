import { describe, expect, it } from "vitest";

import type { NineTurnSeriesDto } from "../api/nineTurnApiTypes";
import { adaptNineTurnSeries } from "./nineTurnAdapter";

describe("adaptNineTurnSeries", () => {
  it.each([
    ["READY", 0, "EMPTY"],
    ["EMPTY", 0, "SOURCE_EMPTY"],
    ["DELAYED", 0, "SOURCE_EMPTY"],
    ["PARTIAL", 1, "PARTIAL"],
  ] as const)("maps %s with %i markers to %s", (status, markerCount, expectedPhase) => {
    const response = series(status, markerCount);

    expect(adaptNineTurnSeries(response, {
      period: "day",
      subjectType: "stock",
      tsCode: "000001.SZ",
    }).phase).toBe(expectedPhase);
  });

  it("rejects an identity, formula, sequence, or time contract drift", () => {
    const wrongFormula = series("READY", 1);
    wrongFormula.meta.formulaVersion = 2 as never;
    const invalidSequence = series("READY", 1);
    invalidSequence.markers[0]!.sequenceNumber = 10 as never;
    const invalidDailyTime = series("READY", 1);
    invalidDailyTime.markers[0]!.tradeTime = "2026-08-13T10:00:00+08:00";

    expect(() => adaptNineTurnSeries(wrongFormula, expected())).toThrow(/公式合同/);
    expect(() => adaptNineTurnSeries(invalidSequence, expected())).toThrow(/marker 合同/);
    expect(() => adaptNineTurnSeries(invalidDailyTime, expected())).toThrow(/时间合同/);
  });

  it("rejects count drift, duplicate time keys, and a stale latest marker", () => {
    const countDrift = series("READY", 1);
    countDrift.meta.markerCount = 0;
    const duplicate = series("READY", 1);
    duplicate.markers.push({ ...duplicate.markers[0]! });
    duplicate.meta.markerCount = 2;
    duplicate.meta.matchedRowCount = 2;
    duplicate.meta.sourceRowCount = 2;
    const staleLatest = series("READY", 1);
    staleLatest.latestMarker = {
      ...staleLatest.markers[0]!,
      sequenceNumber: 4,
    };

    expect(() => adaptNineTurnSeries(countDrift, expected())).toThrow(/数量合同/);
    expect(() => adaptNineTurnSeries(duplicate, expected())).toThrow(/严格升序/);
    expect(() => adaptNineTurnSeries(staleLatest, expected())).toThrow(/latestMarker/);
  });
});

function expected() {
  return { period: "day" as const, subjectType: "stock" as const, tsCode: "000001.SZ" };
}

function series(
  status: NineTurnSeriesDto["dataStatus"]["status"],
  markerCount: number,
): NineTurnSeriesDto {
  const markers = markerCount === 0 ? [] : [{
    completed: false,
    direction: "UP" as const,
    sequenceNumber: 3 as const,
    tradeDate: "2026-08-13",
    tradeTime: null,
  }];
  return {
    dataStatus: {
      code: status === "READY" ? null : "NT_SOURCE_NOT_READY",
      expectedEndDate: "2026-08-13",
      message: null,
      observedEndDate: "2026-08-13",
      status,
    },
    debugInfo: null,
    latestMarker: markers[0] ?? null,
    markers,
    meta: {
      comparisonLag: 4,
      endDate: "2026-08-13",
      formulaVersion: 1,
      hasMore: false,
      limit: 300,
      markerCount: markers.length,
      matchedRowCount: 1,
      missingRowCount: status === "PARTIAL" ? 1 : 0,
      nextCursor: null,
      observedEndDate: "2026-08-13",
      observedStartDate: "2026-08-13",
      signalThreshold: 9,
      sourceRowCount: status === "PARTIAL" ? 2 : 1,
      startDate: null,
    },
    period: "day",
    subjectType: "stock",
    tsCode: "000001.SZ",
  };
}
