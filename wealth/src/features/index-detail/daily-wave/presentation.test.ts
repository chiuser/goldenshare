import { describe, expect, it } from "vitest";
import { dailyWaveEndedFixture, dailyWaveReadyFixture } from "./dailyWaveFixtures.test-support";
import { buildDailyWavePresentation } from "./presentation";
import { decodeDailyWaveResponse } from "./adapter";

describe("daily-wave presentation from published facts", () => {
  it("draws the completed UP pair and only the known start of the open DOWN, keeping shared dates", () => {
    const response = dailyWaveEndedFixture();
    expect(() => decodeDailyWaveResponse(response)).not.toThrow();
    const view = buildDailyWavePresentation(response);
    expect(view.markers.map(({ date, direction }) => [date, direction])).toEqual([
      ["2023-10-24", "UP"], ["2023-10-26", "DOWN"], ["2023-10-26", "UP"],
    ]);
    expect(view.byDate.get("2023-10-26")?.map((fact) => [fact.segment.direction, fact.role])).toEqual([["UP", "end"], ["DOWN", "start"]]);
    expect(view.byDate.get("2023-10-27")?.[0]?.role).toBe("end");
    expect(view.markers.some((marker) => marker.date === "2023-10-27")).toBe(false);
  });
  it("keeps the real start outside observation and never substitutes its left edge", () => {
    const response = dailyWaveReadyFixture();
    const view = buildDailyWavePresentation(response);
    expect(view.markers).toEqual([]);
    expect(view.explanations).toHaveLength(1);
    expect(view.explanations[0]!.reasons).toContain("起始K线在本次观察范围之外，保留实际日期2023-10-23。");
    expect(view.byDate.get("2023-10-23")?.[0]?.role).toBe("start");
    expect(view.byDate.get("2023-10-26")?.[0]?.role).toBe("end");
    expect(view.explanations[0]!.reasons).toContain("这段行情尚未结束，暂不画终止三角。");
  });

  it("merges reasons per segment without losing individual endpoint issues", () => {
    const response = dailyWaveReadyFixture();
    const segment = response.segments[0]!;
    const issue = { date: "2023-10-26", direction: "UP" as const, segmentIds: [segment.id], reason: "SPACE_UNAVAILABLE" as const };
    const view = buildDailyWavePresentation(response, [issue, issue]);
    expect(view.explanations).toHaveLength(1);
    expect(view.explanations[0]!.reasons.filter((reason) => reason.includes("空间不足"))).toEqual([
      "起止K线2023-10-26空间不足，暂未绘制；计算日期保留。",
    ]);
    expect(view.unavailableEndpointCount).toBe(1);
  });

  // Deliberately invalid eligibility input: a future confirmation must not be rendered.
  it("does not paint a pair confirmed after the response as-of time", () => {
    const response = dailyWaveReadyFixture();
    response.segments[0]!.isEnded = true;
    response.segments[0]!.endKnownAt = "2023-10-27T15:00:00+08:00";
    expect(buildDailyWavePresentation(response).markers).toEqual([]);
  });

  it("retains an ungenerated record with its original color dates and no invented K-line", () => {
    const response = dailyWaveReadyFixture();
    const segment = response.segments[0]!;
    // Contract values for the known no-candidate branch (LLD14.6.1).
    Object.assign(segment, { generated: false, start: null, end: null, startKnownAt: null,
      endKnownAt: null, isEnded: false, startValidity: "UNKNOWN", endValidity: "UNKNOWN", endpointValidity: "UNKNOWN",
      extrema: null, internalPriceRelations: null, difTurnIds: [],
      issues: [{ message: "前面行情不足，尚不能确定起始K线。", dates: [] }],
      tailReview: { range: null, turnIds: [], extrema: null, strictlyBrokeStart: null, touchedStart: null } });
    Object.assign(response.mappings[0]!, { priceRange: null, priceObservationIntersection: null, priceTurnIds: [], endpointOffsets: [] });
    response.coverage.ungeneratedPriceSegmentIds = [segment.id];
    response.coverage.unknownPriceSegmentIds = [segment.id];
    response.coverage.counts.ungenerated = 1;
    response.coverage.counts.unknown = 1;
    expect(() => decodeDailyWaveResponse(response)).not.toThrow();
    const view = buildDailyWavePresentation(response);
    expect(view.markers).toEqual([]);
    expect([...view.byDate]).toEqual([]);
    expect(view.explanations[0]).toMatchObject({ colorStart: "2023-10-24", colorEnd: "2023-10-26" });
    expect(view.explanations[0]!.reasons).toContain("前面行情不足，尚不能确定起始K线。");
  });
});
