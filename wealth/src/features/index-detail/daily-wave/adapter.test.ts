import { describe, expect, it } from "vitest";
import { decodeDailyWaveResponse, matchDailyWaveKline } from "./adapter";
import { dailyWaveEmptyFixture, dailyWaveEndedFixture, dailyWaveEndedKlineFixture, dailyWaveKlineFixture,
  dailyWaveNeutralFixture, dailyWaveNeutralKlineFixture, dailyWaveReadyFixture } from "./dailyWaveFixtures.test-support";
import type { DailyWaveReadyResponse } from "./types";

describe("daily-wave HTTP facts", () => {
  it("preserves independent literal facts, all nulls and decimal source text", () => {
    const input = dailyWaveReadyFixture();
    const decoded = decodeDailyWaveResponse(input);
    expect(decoded).toEqual(input);
    expect(decoded).not.toBe(input);
    if (decoded.status !== "ready") throw new Error("literal is ready");
    expect(decoded.segments[0]!.start).toEqual({ date: "2023-10-23", closedAt: "2023-10-23T15:00:00+08:00", close: "100", tiedDates: ["2023-10-23"] });
    expect(decoded.segments[0]!.end?.close).toBe("120");
    expect(decoded.segments[0]!.endKnownAt).toBeNull();
    expect(decoded.colorSegments[0]!.extrema.longestGreen).toEqual({ value: "-2", absoluteLength: "2", dates: ["2023-10-23"] });
    expect(decoded.sourcePoints[1]!.dea).toBe("3.5");
    expect(decoded.pendingTurns[0]!.confirmedAt).toBeNull();
  });
  it("accepts only nine fields for empty, without creating placeholder arrays", () => {
    expect(decodeDailyWaveResponse(dailyWaveEmptyFixture())).toEqual(dailyWaveEmptyFixture());
    expect(() => decodeDailyWaveResponse({ ...dailyWaveEmptyFixture(), segments: [] })).toThrow();
  });
  const faults: Array<[string, (response: DailyWaveReadyResponse) => void]> = [
    ["wrong schema", value => Object.assign(value, { schemaVersion: "1" })],
    ["wrong code", value => Object.assign(value, { tsCode: "399001.SZ" })],
    ["wrong period", value => Object.assign(value, { period: "m90" })],
    ["wrong rule", value => Object.assign(value, { ruleId: "old" })],
    ["wrong requested range", value => Object.assign(value, { requestedEnd: "2026-10-23" })],
    ["old internal name", value => Object.assign(value, { priceSegments: [] })],
    ["internal daily snapshots", value => Object.assign(value, { asofChanges: [] })],
    ["missing required nullable", value => { Reflect.deleteProperty(value.pendingTurns[0]!, "confirmedAt"); }],
    ["numeric decimal", value => Object.assign(value.sourcePoints[0]!, { close: 110 })],
    ["nonfinite decimal", value => { value.sourcePoints[0]!.dif = "Infinity"; }],
    ["negative zero", value => { value.sourcePoints[0]!.dif = "-0"; }],
    ["decimal exponent", value => { value.sourcePoints[0]!.dif = "5e0"; }],
    ["rounded text", value => { value.sourcePoints[0]!.dif = "5.0"; }],
    ["invalid date", value => { value.sourcePoints[0]!.date = "2023-02-30"; }],
    ["duplicate date", value => { value.sourcePoints[1]!.date = "2023-10-24"; }],
    ["reverse dates", value => { value.sourcePoints.reverse(); }],
    ["invalid timezone", value => { value.calculatedAt = "2026-10-26T16:00:00Z"; }],
    ["invalid clock", value => { value.calculatedAt = "2026-10-26T24:00:00+08:00"; }],
    ["wrong asof", value => { value.asOf = "2023-10-26T14:00:00+08:00"; }],
    ["duplicate turn", value => { value.turns.push(value.turns[0]!); }],
    ["confirmed too early", value => { value.turns[0]!.confirmedAt = "2023-10-23T15:00:00+08:00"; }],
    ["confirmed in future", value => { value.turns[0]!.confirmedAt = "2023-10-27T15:00:00+08:00"; }],
    ["unknown pending enum", value => Object.assign(value.pendingTurns[0]!, { possibleKind: "HIGH" })],
    ["duplicate plateau date", value => { value.turns[0]!.plateauDates.push("2023-10-23"); }],
    ["duplicate color", value => { value.colorSegments.push(value.colorSegments[0]!); }],
    ["dangling color turn", value => { value.colorSegments[0]!.turnIds.push("missing"); }],
    ["green absolute length", value => { value.colorSegments[0]!.extrema.longestGreen!.absoluteLength = "3"; }],
    ["green positive sign", value => { value.colorSegments[0]!.extrema.longestGreen!.value = "2"; }],
    ["extrema order", value => { value.colorSegments[0]!.extrema.minClose.value = "101"; }],
    ["open confirmed color", value => { value.colorSegments[1]!.endKnownAt = value.asOf; }],
    ["wrong price source", value => { value.segments[0]!.sourceColorSegmentId = "missing"; }],
    ["duplicate price", value => { value.segments.push(value.segments[0]!); }],
    ["null generated endpoint", value => { value.segments[0]!.start = null; }],
    ["wrong start-known date", value => { value.segments[0]!.startKnownAt = "2023-10-25T15:00:00+08:00"; }],
    ["out-of-search endpoint", value => { value.segments[0]!.start!.tiedDates = ["2023-10-22"]; value.segments[0]!.start!.date = "2023-10-22"; value.segments[0]!.start!.closedAt = "2023-10-22T15:00:00+08:00"; }],
    ["wrong end search", value => { value.segments[0]!.endSearchRange!.startDate = "2023-10-24"; }],
    ["wrong tail interval", value => { value.segments[0]!.tailReview.range!.startDate = "2023-10-25"; }],
    ["price DIF references close turn", value => { value.segments[0]!.difTurnIds.push(value.turns[0]!.id); }],
    ["wrong high/low comparison", value => { value.segments[0]!.internalPriceRelations!.highComparisons = []; }],
    ["wrong insufficient status", value => { value.segments[0]!.internalPriceRelations!.status = "INSUFFICIENT"; }],
    ["missing mapping", value => { value.mappings = []; }],
    ["dangling mapping", value => { value.mappings[0]!.priceSegmentId = "missing"; }],
    ["wrong mapping intersection", value => { value.mappings[0]!.observationIntersection!.startDate = "2023-10-25"; }],
    ["wrong mapping source list", value => { value.mappings[0]!.sourceTurnIds = []; }],
    ["duplicate offsets", value => { value.mappings[0]!.endpointOffsets.push(value.mappings[0]!.endpointOffsets[0]!); }],
    ["wrong offset type", value => Object.assign(value.mappings[0]!.endpointOffsets[0]!, { tradingDayOffset: 0.5 })],
    ["wrong coverage", value => { value.coverage.mainPointCount = 4; }],
    ["wrong coverage count", value => { value.coverage.counts.leftIncomplete = 1; }],
    ["wrong coverage ids", value => { value.coverage.invalidPriceSegmentIds.push(value.segments[0]!.id); }],
    ["unknown nested property", value => Object.assign(value.segments[0]!.tailReview, { path: "/tmp/private" })],
  ];
  it.each(faults)("rejects %s without repairing facts", (_name, corrupt) => {
    const input = dailyWaveReadyFixture(); corrupt(input);
    expect(() => decodeDailyWaveResponse(input)).toThrow("校验失败");
  });
  it("retains ungenerated candidates with exact null meanings", () => {
    const input = dailyWaveReadyFixture(); const segment = input.segments[0]!;
    Object.assign(segment, { generated: false, start: null, end: null, startKnownAt: null, isEnded: false, endKnownAt: null,
      startValidity: "UNKNOWN", endValidity: "UNKNOWN", endpointValidity: "UNKNOWN", extrema: null, internalPriceRelations: null,
      issues: [{ message: "前段不足，起始位置未确定", dates: ["2023-10-24"] }], difTurnIds: [],
      tailReview: { range: null, turnIds: [], extrema: null, strictlyBrokeStart: null, touchedStart: null } });
    Object.assign(input.mappings[0]!, { priceRange: null, priceObservationIntersection: null, priceTurnIds: [], endpointOffsets: [] });
    input.coverage.ungeneratedPriceSegmentIds = [segment.id]; input.coverage.unknownPriceSegmentIds = [segment.id];
    input.coverage.counts.ungenerated = 1; input.coverage.counts.unknown = 1;
    expect(decodeDailyWaveResponse(input)).toEqual(input);
  });
  it("accepts the real pure producer's artificial ended input and independently checks 90/120/dates", () => {
    const decoded = decodeDailyWaveResponse(dailyWaveEndedFixture());
    if (decoded.status !== "ready") throw new Error("expected artificial ready");
    const up = decoded.segments.find(segment => segment.direction === "UP")!;
    const down = decoded.segments.find(segment => segment.direction === "DOWN")!;
    expect([up.start?.date, up.start?.close, up.end?.date, up.end?.close, up.isEnded, up.endKnownAt])
      .toEqual(["2023-10-24", "90", "2023-10-26", "120", true, "2023-10-27T15:00:00+08:00"]);
    expect([down.start?.date, down.start?.close, down.isEnded, down.endKnownAt]).toEqual(["2023-10-26", "120", false, null]);
    expect(matchDailyWaveKline(decoded, dailyWaveEndedKlineFixture()).matched).toBe(true);
  });
  it("keeps zero-only neutral days, pending flat platforms and zero candidates", () => {
    const decoded = decodeDailyWaveResponse(dailyWaveNeutralFixture());
    if (decoded.status !== "ready") throw new Error("expected neutral ready");
    expect(decoded.segments).toEqual([]); expect(decoded.colorSegments).toEqual([]);
    expect(decoded.pendingTurns.map(turn => turn.possibleKind)).toEqual([null, null]);
    expect(matchDailyWaveKline(decoded, dailyWaveNeutralKlineFixture()).matched).toBe(true);
  });
  it.each(["missingColor", "nonDif", "duplicateDif", "wrongCount", "wrongBarLength", "negativeHigh", "badDate", "extraNested"])("rejects %s in complete three-color comparison", fault => {
    const input = dailyWaveEndedFixture(), triple = input.shortOppositeSegments[0]!;
    if (fault === "missingColor") triple.nextColorSegmentId = "missing";
    if (fault === "nonDif") triple.difTurnIds.push(input.turns.find(turn => turn.metric === "CLOSE")!.id);
    if (fault === "duplicateDif") triple.difTurnIds.push(triple.difTurnIds[0]!);
    if (fault === "wrongCount") Object.assign(triple.barStats.previous, { coloredCount: true });
    if (fault === "wrongBarLength") triple.barStats.previous.longestBar.absoluteLength = "999";
    if (fault === "negativeHigh") triple.priceHighs.previous.value = "-1";
    if (fault === "badDate") triple.priceLows.next.dates = ["2023-02-30"];
    if (fault === "extraNested") Object.assign(triple.barStats.next, { threshold: 0.01 });
    expect(() => decodeDailyWaveResponse(input)).toThrow("校验失败");
  });
});

describe("daily-wave exact Kline matching", () => {
  it("preserves all real OHLC and factors, not a fabricated close-only candle", () => {
    const response = dailyWaveReadyFixture(); const kline = dailyWaveKlineFixture();
    const result = matchDailyWaveKline(response, kline);
    expect(result.matched).toBe(true);
    if (!result.matched) return;
    expect(result.candles.map(point => [point.fullDate, point.open, point.high, point.low, point.close, point.dif, point.dea, point.macd]))
      .toEqual([["2023-10-24", 109, 112, 108, 110, 5, 4, 2], ["2023-10-25", 104, 107, 103, 105, 4, 3.5, 1], ["2023-10-26", 119, 122, 118, 120, 7, 6, 2]]);
    expect(response.sourcePoints[0]!.close).toBe("110");
  });
  it("compares numeric meaning, including a 4160.450 source text and 4160.45 Kline", () => {
    const response = dailyWaveReadyFixture(), kline = dailyWaveKlineFixture();
    response.sourcePoints[0]!.close = "4160.450"; kline.bars[0]!.close = 4160.45;
    expect(matchDailyWaveKline(response, kline).matched).toBe(true);
    expect(response.sourcePoints[0]!.close).toBe("4160.450");
  });
  it.each(["close", "dif", "dea", "macd"] as const)("does not hide real %s differences", key => {
    const response = dailyWaveReadyFixture(), kline = dailyWaveKlineFixture();
    if (key === "close") kline.bars[0]!.close = 110.000001;
    else kline.bars[0]!.factors.macd[key] = Number(response.sourcePoints[0]![key]) + 0.000001;
    expect(matchDailyWaveKline(response, kline)).toEqual({ matched: false, message: "行情与研究结果不一致，暂不显示波段" });
  });
  it.each(["missing", "duplicate", "reverse", "wrongDate", "wrongCode", "wrongPeriod", "nonfinite", "null", "numericString"])("rejects %s Kline", fault => {
    const response = dailyWaveReadyFixture(), kline = dailyWaveKlineFixture();
    if (fault === "missing") kline.bars.pop();
    if (fault === "duplicate") kline.bars[1] = kline.bars[0]!;
    if (fault === "reverse") kline.bars.reverse();
    if (fault === "wrongDate") kline.bars[0]!.tradeDate = "2023-10-23";
    if (fault === "wrongCode") kline.indexRef.tsCode = "399001.SZ";
    if (fault === "wrongPeriod") Object.assign(kline, { period: "m90" });
    if (fault === "nonfinite") kline.bars[0]!.factors.macd.dif = Infinity;
    if (fault === "null") kline.bars[0]!.close = null;
    if (fault === "numericString") Object.assign(kline.bars[0]!, { close: "110" });
    expect(matchDailyWaveKline(response, kline).matched).toBe(false);
  });
});
