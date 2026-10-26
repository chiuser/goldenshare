import { describe, expect, it } from "vitest";
import { dailyWaveEndedFixture, dailyWaveReadyFixture, dailyWaveSharedLowFixture } from "./dailyWaveFixtures.test-support";
import { buildDailyWavePresentation } from "./presentation";
import { decodeDailyWaveResponse } from "./adapter";
import { resolveDailyWaveMarkerLayout } from "./markerGeometry";

const highUp = "000001.SH:day:RED:2023-10-24:PRICE:UP";
const highDown = "000001.SH:day:GREEN:2023-10-27:PRICE:DOWN";
const lowDown = "000001.SH:day:GREEN:2023-10-24:PRICE:DOWN";
const lowUp = "000001.SH:day:RED:2023-10-27:PRICE:UP";

describe("daily-wave presentation from published facts", () => {
  it("draws one green high-point triangle for UP end and the following open DOWN start", () => {
    const response = dailyWaveEndedFixture();
    expect(() => decodeDailyWaveResponse(response)).not.toThrow();
    const original = structuredClone(response);
    const view = buildDailyWavePresentation(response);
    expect(view.markers).toEqual([
      { date: "2023-10-24", direction: "UP", segmentIds: [highUp] },
      { date: "2023-10-26", direction: "DOWN", segmentIds: [highUp, highDown] },
    ]);
    expect(view.byDate.get("2023-10-26")?.map((fact) => [fact.segment.direction, fact.role])).toEqual([["UP", "end"], ["DOWN", "start"]]);
    expect(view.byDate.get("2023-10-27")?.[0]?.role).toBe("end");
    expect(view.markers.some((marker) => marker.date === "2023-10-27")).toBe(false);
    expect(response).toEqual(original);
    expect(buildDailyWavePresentation({ ...response, segments: [...response.segments].reverse() }).markers).toEqual(view.markers);
  });

  it("draws one red low-point triangle while keeping DOWN 120-to-90 and UP starting at 90", () => {
    const response = dailyWaveSharedLowFixture();
    expect(() => decodeDailyWaveResponse(response)).not.toThrow();
    const original = structuredClone(response);
    const view = buildDailyWavePresentation(response);
    expect(view.markers).toEqual([
      { date: "2023-10-24", direction: "DOWN", segmentIds: [lowDown] },
      { date: "2023-10-26", direction: "UP", segmentIds: [lowDown, lowUp] },
    ]);
    expect(view.byDate.get("2023-10-26")?.map(({ segment, role }) => [segment.id, role, segment[role]?.close])).toEqual([
      [lowDown, "end", "90"], [lowUp, "start", "90"],
    ]);
    expect(response).toEqual(original);
  });

  // Deliberately altered projection inputs below isolate non-matching or ineligible
  // roles. They are negative presentation tests, not accepted HTTP fixtures.
  it("does not merge opposite endpoints on the same date without the predecessor relationship", () => {
    const response = dailyWaveEndedFixture();
    response.segments[1]!.previousColorSegmentId = response.colorSegments[0]!.id;
    const shared = buildDailyWavePresentation(response).markers.filter((m) => m.date === "2023-10-26");
    expect(shared).toEqual([
      { date: "2023-10-26", direction: "DOWN", segmentIds: [highDown] },
      { date: "2023-10-26", direction: "UP", segmentIds: [highUp] },
    ]);
  });

  it("does not move the following start to manufacture a shared date", () => {
    const response = dailyWaveEndedFixture();
    response.segments[1]!.start!.date = "2023-10-25";
    expect(buildDailyWavePresentation(response).markers.map((m) => [m.date, m.direction])).toEqual([
      ["2023-10-24", "UP"], ["2023-10-25", "DOWN"], ["2023-10-26", "UP"],
    ]);
  });

  it.each(["start", "end"] as const)("does not join two %s roles into a shared turn", (role) => {
    const response = dailyWaveEndedFixture();
    const [first, next] = response.segments;
    if (role === "start") {
      first!.isEnded = false;
      first!.start = { ...first!.end! };
    } else {
      next!.isEnded = true;
      next!.endKnownAt = response.asOf;
      next!.start = { ...next!.start!, date: "2023-10-25" };
      next!.end = { ...first!.end! };
    }
    expect(buildDailyWavePresentation(response).markers.filter((m) => m.date === "2023-10-26").map((m) => m.direction)).toEqual(["DOWN", "UP"]);
  });

  it.each(["open", "invalid", "future"] as const)("never borrows eligibility for a %s previous end", (state) => {
    const response = dailyWaveEndedFixture();
    const previous = response.segments[0]!;
    if (state === "open") previous.isEnded = false;
    if (state === "invalid") previous.endpointValidity = "INVALID";
    if (state === "future") previous.endKnownAt = "2023-10-30T15:00:00+08:00";
    expect(buildDailyWavePresentation(response).markers.filter((m) => m.date === "2023-10-26")).toEqual([
      { date: "2023-10-26", direction: "DOWN", segmentIds: [highDown] },
    ]);
  });

  it("keeps an unrelated same-day UP start outside a valid UP-end/DOWN-start pair", () => {
    const response = dailyWaveEndedFixture();
    const independent = structuredClone(response.segments[0]!);
    Object.assign(independent, { id: "independent-up", isEnded: false, start: { ...independent.end! } });
    response.segments.push(independent);
    expect(buildDailyWavePresentation(response).markers.filter((m) => m.date === "2023-10-26")).toEqual([
      { date: "2023-10-26", direction: "DOWN", segmentIds: [highUp, highDown] },
      { date: "2023-10-26", direction: "UP", segmentIds: ["independent-up"] },
    ]);
  });

  it("continues grouping independent same-direction starts without dropping their IDs", () => {
    const response = dailyWaveEndedFixture();
    const independent = structuredClone(response.segments[0]!);
    Object.assign(independent, { id: "independent-up", isEnded: false });
    response.segments.push(independent);
    const view = buildDailyWavePresentation(response);
    expect(view.markers.find((m) => m.date === "2023-10-24")).toEqual({
      date: "2023-10-24", direction: "UP", segmentIds: [highUp, "independent-up"],
    });
    expect(buildDailyWavePresentation({ ...response, segments: [...response.segments].reverse() }).markers).toEqual(view.markers);
  });

  it("reports one blocked shared triangle to both segments without removing their original facts", () => {
    const response = dailyWaveEndedFixture();
    const view = buildDailyWavePresentation(response);
    const shared = view.markers.find((m) => m.date === "2023-10-26")!;
    const placed = resolveDailyWaveMarkerLayout({ markers: [{ ...shared, x: 100, anchorY: 100 }],
      occupied: [{ left: 0, top: 0, width: 300, height: 200 }], width: 300, height: 200 });
    expect(placed.layouts).toEqual([]);
    expect(placed.issues).toEqual([{ date: "2023-10-26", direction: "DOWN", segmentIds: [highUp, highDown], reason: "SPACE_UNAVAILABLE" }]);
    const blocked = buildDailyWavePresentation(response, placed.issues);
    expect(blocked.unavailableEndpointCount).toBe(1);
    expect(blocked.spaceUnavailableEndpointCount).toBe(1);
    expect(blocked.explanations.filter((e) => e.reasons.some((r) => r.includes("空间不足"))).map((e) => e.segment.id)).toEqual([highUp, highDown]);
    expect(blocked.byDate).toEqual(view.byDate);
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
