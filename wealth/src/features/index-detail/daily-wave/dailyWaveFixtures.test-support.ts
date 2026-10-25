import type { IndexDetailKlineResponseDto } from "../api/indexDetailApiTypes";
import type { DailyWaveEmptyResponse, DailyWaveReadyResponse } from "./types";

// Independent literal example from LLD 14.6.1/14.7 and the published Python DTO.
// Green 100 precedes red 110 -> 105 -> 120; no calculator/parser generates expected facts.
const close23 = "000001.SH:day:CLOSE:2023-10-23", close24 = "000001.SH:day:CLOSE:2023-10-24";
const close25 = "000001.SH:day:CLOSE:2023-10-25", close26 = "000001.SH:day:CLOSE:2023-10-26";
const dif23 = "000001.SH:day:DIF:2023-10-23", dif24 = "000001.SH:day:DIF:2023-10-24";
const dif25 = "000001.SH:day:DIF:2023-10-25", dif26 = "000001.SH:day:DIF:2023-10-26";
const green = "000001.SH:day:GREEN:2023-10-23", red = "000001.SH:day:RED:2023-10-24";
const price = `${red}:PRICE:UP`;
const stamp = (day: string) => `${day}T15:00:00+08:00`;
const redExtrema = {
  maxClose: { value: "120", dates: ["2023-10-26"] }, minClose: { value: "105", dates: ["2023-10-25"] },
  maxDif: { value: "7", dates: ["2023-10-26"] }, minDif: { value: "4", dates: ["2023-10-25"] },
  longestRed: { value: "2", absoluteLength: "2", dates: ["2023-10-24", "2023-10-26"] }, longestGreen: null,
};
const literalReady: DailyWaveReadyResponse = {
  schemaVersion: 1, tsCode: "000001.SH", period: "day", status: "ready", ruleId: "xxm-daily-wave-review-v0.1",
  calculationId: "literal-review", calculatedAt: "2026-10-26T16:00:00.123456+08:00",
  requestedStart: "2023-10-24", requestedEnd: "2026-10-21", observationStart: "2023-10-24", observationEnd: "2023-10-26",
  contextStart: "2023-10-23", contextEnd: "2023-10-26", asOf: stamp("2023-10-26"),
  sourcePoints: [
    { date: "2023-10-24", close: "110", dif: "5", dea: "4", macd: "2" },
    { date: "2023-10-25", close: "105", dif: "4", dea: "3.5", macd: "1" },
    { date: "2023-10-26", close: "120", dif: "7", dea: "6", macd: "2" },
  ],
  turns: [
    { id: close23, metric: "CLOSE", kind: "MIN", value: "100", firstDate: "2023-10-23", lastDate: "2023-10-23", plateauDates: ["2023-10-23"], confirmedAt: stamp("2023-10-24") },
    { id: dif23, metric: "DIF", kind: "MIN", value: "4", firstDate: "2023-10-23", lastDate: "2023-10-23", plateauDates: ["2023-10-23"], confirmedAt: stamp("2023-10-24") },
    { id: close24, metric: "CLOSE", kind: "MAX", value: "110", firstDate: "2023-10-24", lastDate: "2023-10-24", plateauDates: ["2023-10-24"], confirmedAt: stamp("2023-10-25") },
    { id: dif24, metric: "DIF", kind: "MAX", value: "5", firstDate: "2023-10-24", lastDate: "2023-10-24", plateauDates: ["2023-10-24"], confirmedAt: stamp("2023-10-25") },
    { id: close25, metric: "CLOSE", kind: "MIN", value: "105", firstDate: "2023-10-25", lastDate: "2023-10-25", plateauDates: ["2023-10-25"], confirmedAt: stamp("2023-10-26") },
    { id: dif25, metric: "DIF", kind: "MIN", value: "4", firstDate: "2023-10-25", lastDate: "2023-10-25", plateauDates: ["2023-10-25"], confirmedAt: stamp("2023-10-26") },
  ],
  pendingTurns: [
    { id: close26, metric: "CLOSE", kind: null, confirmedAt: null, possibleKind: "MAX", value: "120", firstDate: "2023-10-26", lastDate: "2023-10-26", plateauDates: ["2023-10-26"] },
    { id: dif26, metric: "DIF", kind: null, confirmedAt: null, possibleKind: "MAX", value: "7", firstDate: "2023-10-26", lastDate: "2023-10-26", plateauDates: ["2023-10-26"] },
  ],
  colorSegments: [
    { id: green, color: "GREEN", startDate: "2023-10-23", endDate: "2023-10-23", lastColoredDate: "2023-10-23", coloredCount: 1,
      zeroDates: [], isLeftComplete: false, isEnded: true, endKnownAt: stamp("2023-10-24"), turnIds: [close23, dif23],
      extrema: { maxClose: { value: "100", dates: ["2023-10-23"] }, minClose: { value: "100", dates: ["2023-10-23"] },
        maxDif: { value: "4", dates: ["2023-10-23"] }, minDif: { value: "4", dates: ["2023-10-23"] },
        longestRed: null, longestGreen: { value: "-2", absoluteLength: "2", dates: ["2023-10-23"] } } },
    { id: red, color: "RED", startDate: "2023-10-24", endDate: "2023-10-26", lastColoredDate: "2023-10-26", coloredCount: 3,
      zeroDates: [], isLeftComplete: true, isEnded: false, endKnownAt: null,
      turnIds: [close24, dif24, close25, dif25, close26, dif26], extrema: redExtrema },
  ],
  segments: [{ id: price, sourceColorSegmentId: red, previousColorSegmentId: green, direction: "UP", generated: true,
    startSearchRange: { startDate: "2023-10-23", endDate: "2023-10-24" }, endSearchRange: { startDate: "2023-10-23", endDate: "2023-10-26" },
    start: { date: "2023-10-23", closedAt: stamp("2023-10-23"), close: "100", tiedDates: ["2023-10-23"] },
    end: { date: "2023-10-26", closedAt: stamp("2023-10-26"), close: "120", tiedDates: ["2023-10-26"] },
    startKnownAt: stamp("2023-10-24"), isEnded: false, endKnownAt: null, startValidity: "VALID", endValidity: "VALID", endpointValidity: "VALID", issues: [],
    internalPriceRelations: { highs: [{ date: "2023-10-24", close: "110" }, { date: "2023-10-26", close: "120" }],
      lows: [{ date: "2023-10-23", close: "100" }, { date: "2023-10-25", close: "105" }],
      highComparisons: [{ fromDate: "2023-10-24", toDate: "2023-10-26", relation: "HIGHER" }],
      lowComparisons: [{ fromDate: "2023-10-23", toDate: "2023-10-25", relation: "HIGHER" }], status: "RISING" },
    tailReview: { range: { startDate: "2023-10-26", endDate: "2023-10-26" }, turnIds: [close26, dif26], strictlyBrokeStart: false, touchedStart: false,
      extrema: { maxClose: { value: "120", dates: ["2023-10-26"] }, minClose: { value: "120", dates: ["2023-10-26"] },
        maxDif: { value: "7", dates: ["2023-10-26"] }, minDif: { value: "7", dates: ["2023-10-26"] },
        longestRed: { value: "2", absoluteLength: "2", dates: ["2023-10-26"] }, longestGreen: null } },
    extrema: { ...redExtrema, minClose: { value: "100", dates: ["2023-10-23"] }, minDif: { value: "4", dates: ["2023-10-23", "2023-10-25"] },
      longestGreen: { value: "-2", absoluteLength: "2", dates: ["2023-10-23"] } }, difTurnIds: [dif23, dif24, dif25, dif26] }],
  mappings: [{ sourceColorSegmentId: red, priceSegmentId: price,
    colorRange: { startDate: "2023-10-24", endDate: "2023-10-26" }, priceRange: { startDate: "2023-10-23", endDate: "2023-10-26" },
    observationIntersection: { startDate: "2023-10-24", endDate: "2023-10-26" }, priceObservationIntersection: { startDate: "2023-10-24", endDate: "2023-10-26" },
    sourceTurnIds: [close24, dif24, close25, dif25, close26, dif26], priceTurnIds: [close23, dif23, close24, dif24, close25, dif25, close26, dif26],
    endpointOffsets: [{ difTurnId: dif23, priceEndpoint: "START", tradingDayOffset: 0 }], issues: [] }],
  shortOppositeSegments: [],
  coverage: { mainPointCount: 3, leftIncompleteColorSegmentIds: [], ungeneratedPriceSegmentIds: [], invalidPriceSegmentIds: [], unknownPriceSegmentIds: [],
    counts: { leftIncomplete: 0, ungenerated: 0, invalid: 0, unknown: 0 } },
};

export function dailyWaveReadyFixture(calculationId = "literal-review"): DailyWaveReadyResponse {
  return { ...structuredClone(literalReady), calculationId };
}
export function dailyWaveEmptyFixture(): DailyWaveEmptyResponse {
  return { schemaVersion: 1, tsCode: "000001.SH", period: "day", status: "empty", ruleId: "xxm-daily-wave-review-v0.1",
    calculationId: "literal-empty", calculatedAt: "2026-10-26T16:00:00+08:00", requestedStart: "2023-10-24", requestedEnd: "2026-10-21" };
}
export function dailyWaveKlineFixture(): IndexDetailKlineResponseDto {
  return {
    pageContext: { tradeDate: "2023-10-26", prevTradeDate: "2023-10-25", isTradingDay: true, sessionStatus: "CLOSED", market: "CN_A", timezone: "Asia/Shanghai", generatedAt: "2023-10-26T15:00:00+08:00", source: "explicit" },
    indexRef: { tsCode: "000001.SH", name: "上证指数" }, period: "day",
    bars: [
      { date: "2023-10-24", close: 110, dif: 5, dea: 4, macd: 2 },
      { date: "2023-10-25", close: 105, dif: 4, dea: 3.5, macd: 1 },
      { date: "2023-10-26", close: 120, dif: 7, dea: 6, macd: 2 },
    ].map(point => ({ tradeDate: point.date, open: point.close - 1, high: point.close + 2, low: point.close - 2,
      close: point.close, preClose: point.close - 1, change: 1, changePct: 1, amplitude: 4, vol: 100, volDisplay: "100手", amount: 1000,
      factors: { ma: { ma5: null, ma10: null, ma20: null, ma30: null, ma60: null, ma90: null, ma250: null },
        boll: { upper: null, middle: null, lower: null }, macd: { dif: point.dif, dea: point.dea, macd: point.macd }, kdj: { k: null, d: null, j: null } } })),
    meta: { count: 3, limit: 1000, startDate: "2023-10-24", endDate: "2023-10-26" },
    dataStatus: { status: "READY", expectedTradeDate: "2023-10-26", observedTradeDate: "2023-10-26" }, debugInfo: null,
  };
}

export function dailyWaveEndedKlineFixture(): IndexDetailKlineResponseDto {
  const response = dailyWaveKlineFixture();
  Object.assign(response.bars[0]!, { open: 89, high: 92, low: 88, close: 90 });
  const last = structuredClone(response.bars[2]!);
  Object.assign(last, { tradeDate: "2023-10-27", open: 120, high: 121, low: 118, close: 119, preClose: 120, change: -1, changePct: -0.83 });
  last.factors.macd = { dif: 6, dea: 6.5, macd: -1 };
  response.bars.push(last);
  response.meta.count = 4; response.meta.endDate = "2023-10-27";
  Object.assign(response.pageContext, { tradeDate: "2023-10-27", prevTradeDate: "2023-10-26", generatedAt: "2023-10-27T15:00:00+08:00" });
  Object.assign(response.dataStatus, { expectedTradeDate: "2023-10-27", observedTradeDate: "2023-10-27" });
  return response;
}

export function dailyWaveNeutralFixture(): DailyWaveReadyResponse {
  // Four completed neutral days, including the context day: no color or candidate.
  return {
    ...dailyWaveEmptyFixture(), status: "ready", calculationId: "literal-neutral",
    observationStart: "2023-10-24", observationEnd: "2023-10-26", contextStart: "2023-10-23", contextEnd: "2023-10-26", asOf: stamp("2023-10-26"),
    sourcePoints: ["2023-10-24", "2023-10-25", "2023-10-26"].map(date => ({ date, close: "100", dif: "0", dea: "0", macd: "0" })),
    turns: [], pendingTurns: [
      { id: "000001.SH:day:CLOSE:2023-10-23", metric: "CLOSE", value: "100", kind: null, confirmedAt: null, possibleKind: null,
        firstDate: "2023-10-23", lastDate: "2023-10-26", plateauDates: ["2023-10-23", "2023-10-24", "2023-10-25", "2023-10-26"] },
      { id: "000001.SH:day:DIF:2023-10-23", metric: "DIF", value: "0", kind: null, confirmedAt: null, possibleKind: null,
        firstDate: "2023-10-23", lastDate: "2023-10-26", plateauDates: ["2023-10-23", "2023-10-24", "2023-10-25", "2023-10-26"] },
    ], colorSegments: [], segments: [], mappings: [], shortOppositeSegments: [],
    coverage: { mainPointCount: 3, leftIncompleteColorSegmentIds: [], ungeneratedPriceSegmentIds: [], invalidPriceSegmentIds: [], unknownPriceSegmentIds: [],
      counts: { leftIncomplete: 0, ungenerated: 0, invalid: 0, unknown: 0 } },
  };
}
export function dailyWaveNeutralKlineFixture(): IndexDetailKlineResponseDto {
  const response = dailyWaveKlineFixture();
  response.bars.forEach(bar => { Object.assign(bar, { close: 100, open: 99, high: 102, low: 98, preClose: 99 }); bar.factors.macd = { dif: 0, dea: 0, macd: 0 }; });
  return response;
}

// Input from the unchanged pure producer for six explicitly hand-authored rows.
// Expected UP 10-24/90 -> 10-26/120, known 10-27, is asserted as literal test data.
const literalEnded: DailyWaveReadyResponse = {"schemaVersion":1,"tsCode":"000001.SH","period":"day","status":"ready","ruleId":"xxm-daily-wave-review-v0.1","calculationId":"literal-ended-review","calculatedAt":"2026-10-26T16:00:00+08:00","requestedStart":"2023-10-24","requestedEnd":"2026-10-21","observationStart":"2023-10-24","observationEnd":"2023-10-27","contextStart":"2023-10-20","contextEnd":"2023-10-27","asOf":"2023-10-27T15:00:00+08:00","sourcePoints":[{"date":"2023-10-24","close":"90","dif":"5","dea":"4","macd":"2"},{"date":"2023-10-25","close":"105","dif":"4","dea":"3.5","macd":"1"},{"date":"2023-10-26","close":"120","dif":"7","dea":"6","macd":"2"},{"date":"2023-10-27","close":"119","dif":"6","dea":"6.5","macd":"-1"}],"turns":[{"id":"000001.SH:day:DIF:2023-10-23","metric":"DIF","kind":"MIN","value":"4","firstDate":"2023-10-23","lastDate":"2023-10-23","plateauDates":["2023-10-23"],"confirmedAt":"2023-10-24T15:00:00+08:00"},{"id":"000001.SH:day:CLOSE:2023-10-24","metric":"CLOSE","kind":"MIN","value":"90","firstDate":"2023-10-24","lastDate":"2023-10-24","plateauDates":["2023-10-24"],"confirmedAt":"2023-10-25T15:00:00+08:00"},{"id":"000001.SH:day:DIF:2023-10-24","metric":"DIF","kind":"MAX","value":"5","firstDate":"2023-10-24","lastDate":"2023-10-24","plateauDates":["2023-10-24"],"confirmedAt":"2023-10-25T15:00:00+08:00"},{"id":"000001.SH:day:DIF:2023-10-25","metric":"DIF","kind":"MIN","value":"4","firstDate":"2023-10-25","lastDate":"2023-10-25","plateauDates":["2023-10-25"],"confirmedAt":"2023-10-26T15:00:00+08:00"},{"id":"000001.SH:day:CLOSE:2023-10-26","metric":"CLOSE","kind":"MAX","value":"120","firstDate":"2023-10-26","lastDate":"2023-10-26","plateauDates":["2023-10-26"],"confirmedAt":"2023-10-27T15:00:00+08:00"},{"id":"000001.SH:day:DIF:2023-10-26","metric":"DIF","kind":"MAX","value":"7","firstDate":"2023-10-26","lastDate":"2023-10-26","plateauDates":["2023-10-26"],"confirmedAt":"2023-10-27T15:00:00+08:00"}],"pendingTurns":[{"id":"000001.SH:day:CLOSE:2023-10-27","metric":"CLOSE","kind":null,"value":"119","firstDate":"2023-10-27","lastDate":"2023-10-27","plateauDates":["2023-10-27"],"confirmedAt":null,"possibleKind":"MIN"},{"id":"000001.SH:day:DIF:2023-10-27","metric":"DIF","kind":null,"value":"6","firstDate":"2023-10-27","lastDate":"2023-10-27","plateauDates":["2023-10-27"],"confirmedAt":null,"possibleKind":"MIN"}],"colorSegments":[{"id":"000001.SH:day:RED:2023-10-20","color":"RED","startDate":"2023-10-20","endDate":"2023-10-20","lastColoredDate":"2023-10-20","coloredCount":1,"zeroDates":[],"isLeftComplete":false,"isEnded":true,"endKnownAt":"2023-10-23T15:00:00+08:00","turnIds":[],"extrema":{"maxClose":{"value":"101","dates":["2023-10-20"]},"minClose":{"value":"101","dates":["2023-10-20"]},"maxDif":{"value":"5","dates":["2023-10-20"]},"minDif":{"value":"5","dates":["2023-10-20"]},"longestRed":{"value":"2","absoluteLength":"2","dates":["2023-10-20"]},"longestGreen":null}},{"id":"000001.SH:day:GREEN:2023-10-23","color":"GREEN","startDate":"2023-10-23","endDate":"2023-10-23","lastColoredDate":"2023-10-23","coloredCount":1,"zeroDates":[],"isLeftComplete":true,"isEnded":true,"endKnownAt":"2023-10-24T15:00:00+08:00","turnIds":["000001.SH:day:DIF:2023-10-23"],"extrema":{"maxClose":{"value":"100","dates":["2023-10-23"]},"minClose":{"value":"100","dates":["2023-10-23"]},"maxDif":{"value":"4","dates":["2023-10-23"]},"minDif":{"value":"4","dates":["2023-10-23"]},"longestRed":null,"longestGreen":{"value":"-2","absoluteLength":"2","dates":["2023-10-23"]}}},{"id":"000001.SH:day:RED:2023-10-24","color":"RED","startDate":"2023-10-24","endDate":"2023-10-26","lastColoredDate":"2023-10-26","coloredCount":3,"zeroDates":[],"isLeftComplete":true,"isEnded":true,"endKnownAt":"2023-10-27T15:00:00+08:00","turnIds":["000001.SH:day:CLOSE:2023-10-24","000001.SH:day:DIF:2023-10-24","000001.SH:day:DIF:2023-10-25","000001.SH:day:CLOSE:2023-10-26","000001.SH:day:DIF:2023-10-26"],"extrema":{"maxClose":{"value":"120","dates":["2023-10-26"]},"minClose":{"value":"90","dates":["2023-10-24"]},"maxDif":{"value":"7","dates":["2023-10-26"]},"minDif":{"value":"4","dates":["2023-10-25"]},"longestRed":{"value":"2","absoluteLength":"2","dates":["2023-10-24","2023-10-26"]},"longestGreen":null}},{"id":"000001.SH:day:GREEN:2023-10-27","color":"GREEN","startDate":"2023-10-27","endDate":"2023-10-27","lastColoredDate":"2023-10-27","coloredCount":1,"zeroDates":[],"isLeftComplete":true,"isEnded":false,"endKnownAt":null,"turnIds":["000001.SH:day:CLOSE:2023-10-27","000001.SH:day:DIF:2023-10-27"],"extrema":{"maxClose":{"value":"119","dates":["2023-10-27"]},"minClose":{"value":"119","dates":["2023-10-27"]},"maxDif":{"value":"6","dates":["2023-10-27"]},"minDif":{"value":"6","dates":["2023-10-27"]},"longestRed":null,"longestGreen":{"value":"-1","absoluteLength":"1","dates":["2023-10-27"]}}}],"mappings":[{"sourceColorSegmentId":"000001.SH:day:RED:2023-10-24","priceSegmentId":"000001.SH:day:RED:2023-10-24:PRICE:UP","colorRange":{"startDate":"2023-10-24","endDate":"2023-10-26"},"priceRange":{"startDate":"2023-10-24","endDate":"2023-10-26"},"observationIntersection":{"startDate":"2023-10-24","endDate":"2023-10-26"},"priceObservationIntersection":{"startDate":"2023-10-24","endDate":"2023-10-26"},"sourceTurnIds":["000001.SH:day:CLOSE:2023-10-24","000001.SH:day:DIF:2023-10-24","000001.SH:day:DIF:2023-10-25","000001.SH:day:CLOSE:2023-10-26","000001.SH:day:DIF:2023-10-26"],"priceTurnIds":["000001.SH:day:CLOSE:2023-10-24","000001.SH:day:DIF:2023-10-24","000001.SH:day:DIF:2023-10-25","000001.SH:day:CLOSE:2023-10-26","000001.SH:day:DIF:2023-10-26"],"endpointOffsets":[{"difTurnId":"000001.SH:day:DIF:2023-10-24","priceEndpoint":"START","tradingDayOffset":0},{"difTurnId":"000001.SH:day:DIF:2023-10-24","priceEndpoint":"END","tradingDayOffset":2},{"difTurnId":"000001.SH:day:DIF:2023-10-25","priceEndpoint":"START","tradingDayOffset":-1},{"difTurnId":"000001.SH:day:DIF:2023-10-25","priceEndpoint":"END","tradingDayOffset":1},{"difTurnId":"000001.SH:day:DIF:2023-10-26","priceEndpoint":"START","tradingDayOffset":-2},{"difTurnId":"000001.SH:day:DIF:2023-10-26","priceEndpoint":"END","tradingDayOffset":0}],"issues":[]},{"sourceColorSegmentId":"000001.SH:day:GREEN:2023-10-27","priceSegmentId":"000001.SH:day:GREEN:2023-10-27:PRICE:DOWN","colorRange":{"startDate":"2023-10-27","endDate":"2023-10-27"},"priceRange":{"startDate":"2023-10-26","endDate":"2023-10-27"},"observationIntersection":{"startDate":"2023-10-27","endDate":"2023-10-27"},"priceObservationIntersection":{"startDate":"2023-10-26","endDate":"2023-10-27"},"sourceTurnIds":["000001.SH:day:CLOSE:2023-10-27","000001.SH:day:DIF:2023-10-27"],"priceTurnIds":["000001.SH:day:CLOSE:2023-10-26","000001.SH:day:DIF:2023-10-26","000001.SH:day:CLOSE:2023-10-27","000001.SH:day:DIF:2023-10-27"],"endpointOffsets":[{"difTurnId":"000001.SH:day:DIF:2023-10-26","priceEndpoint":"START","tradingDayOffset":0},{"difTurnId":"000001.SH:day:DIF:2023-10-26","priceEndpoint":"END","tradingDayOffset":1},{"difTurnId":"000001.SH:day:DIF:2023-10-27","priceEndpoint":"START","tradingDayOffset":-1},{"difTurnId":"000001.SH:day:DIF:2023-10-27","priceEndpoint":"END","tradingDayOffset":0}],"issues":[]}],"shortOppositeSegments":[{"previousColorSegmentId":"000001.SH:day:RED:2023-10-20","oppositeColorSegmentId":"000001.SH:day:GREEN:2023-10-23","nextColorSegmentId":"000001.SH:day:RED:2023-10-24","barStats":{"previous":{"coloredCount":1,"longestBar":{"value":"2","absoluteLength":"2","dates":["2023-10-20"]}},"opposite":{"coloredCount":1,"longestBar":{"value":"-2","absoluteLength":"2","dates":["2023-10-23"]}},"next":{"coloredCount":3,"longestBar":{"value":"2","absoluteLength":"2","dates":["2023-10-24","2023-10-26"]}}},"priceHighs":{"previous":{"value":"101","dates":["2023-10-20"]},"opposite":{"value":"100","dates":["2023-10-23"]},"next":{"value":"120","dates":["2023-10-26"]}},"priceLows":{"previous":{"value":"101","dates":["2023-10-20"]},"opposite":{"value":"100","dates":["2023-10-23"]},"next":{"value":"90","dates":["2023-10-24"]}},"difTurnIds":["000001.SH:day:DIF:2023-10-23","000001.SH:day:DIF:2023-10-24","000001.SH:day:DIF:2023-10-25","000001.SH:day:DIF:2023-10-26"]},{"previousColorSegmentId":"000001.SH:day:GREEN:2023-10-23","oppositeColorSegmentId":"000001.SH:day:RED:2023-10-24","nextColorSegmentId":"000001.SH:day:GREEN:2023-10-27","barStats":{"previous":{"coloredCount":1,"longestBar":{"value":"-2","absoluteLength":"2","dates":["2023-10-23"]}},"opposite":{"coloredCount":3,"longestBar":{"value":"2","absoluteLength":"2","dates":["2023-10-24","2023-10-26"]}},"next":{"coloredCount":1,"longestBar":{"value":"-1","absoluteLength":"1","dates":["2023-10-27"]}}},"priceHighs":{"previous":{"value":"100","dates":["2023-10-23"]},"opposite":{"value":"120","dates":["2023-10-26"]},"next":{"value":"119","dates":["2023-10-27"]}},"priceLows":{"previous":{"value":"100","dates":["2023-10-23"]},"opposite":{"value":"90","dates":["2023-10-24"]},"next":{"value":"119","dates":["2023-10-27"]}},"difTurnIds":["000001.SH:day:DIF:2023-10-23","000001.SH:day:DIF:2023-10-24","000001.SH:day:DIF:2023-10-25","000001.SH:day:DIF:2023-10-26","000001.SH:day:DIF:2023-10-27"]}],"coverage":{"mainPointCount":4,"leftIncompleteColorSegmentIds":[],"ungeneratedPriceSegmentIds":[],"invalidPriceSegmentIds":[],"unknownPriceSegmentIds":[],"counts":{"leftIncomplete":0,"ungenerated":0,"invalid":0,"unknown":0}},"segments":[{"id":"000001.SH:day:RED:2023-10-24:PRICE:UP","sourceColorSegmentId":"000001.SH:day:RED:2023-10-24","previousColorSegmentId":"000001.SH:day:GREEN:2023-10-23","direction":"UP","generated":true,"startSearchRange":{"startDate":"2023-10-23","endDate":"2023-10-24"},"endSearchRange":{"startDate":"2023-10-24","endDate":"2023-10-26"},"start":{"date":"2023-10-24","closedAt":"2023-10-24T15:00:00+08:00","close":"90","tiedDates":["2023-10-24"]},"end":{"date":"2023-10-26","closedAt":"2023-10-26T15:00:00+08:00","close":"120","tiedDates":["2023-10-26"]},"startKnownAt":"2023-10-24T15:00:00+08:00","isEnded":true,"endKnownAt":"2023-10-27T15:00:00+08:00","startValidity":"VALID","endValidity":"VALID","endpointValidity":"VALID","issues":[],"internalPriceRelations":{"highs":[{"date":"2023-10-26","close":"120"}],"lows":[{"date":"2023-10-24","close":"90"}],"highComparisons":[],"lowComparisons":[],"status":"INSUFFICIENT"},"tailReview":{"range":{"startDate":"2023-10-26","endDate":"2023-10-26"},"turnIds":["000001.SH:day:CLOSE:2023-10-26","000001.SH:day:DIF:2023-10-26"],"extrema":{"maxClose":{"value":"120","dates":["2023-10-26"]},"minClose":{"value":"120","dates":["2023-10-26"]},"maxDif":{"value":"7","dates":["2023-10-26"]},"minDif":{"value":"7","dates":["2023-10-26"]},"longestRed":{"value":"2","absoluteLength":"2","dates":["2023-10-26"]},"longestGreen":null},"strictlyBrokeStart":false,"touchedStart":false},"extrema":{"maxClose":{"value":"120","dates":["2023-10-26"]},"minClose":{"value":"90","dates":["2023-10-24"]},"maxDif":{"value":"7","dates":["2023-10-26"]},"minDif":{"value":"4","dates":["2023-10-25"]},"longestRed":{"value":"2","absoluteLength":"2","dates":["2023-10-24","2023-10-26"]},"longestGreen":null},"difTurnIds":["000001.SH:day:DIF:2023-10-24","000001.SH:day:DIF:2023-10-25","000001.SH:day:DIF:2023-10-26"]},{"id":"000001.SH:day:GREEN:2023-10-27:PRICE:DOWN","sourceColorSegmentId":"000001.SH:day:GREEN:2023-10-27","previousColorSegmentId":"000001.SH:day:RED:2023-10-24","direction":"DOWN","generated":true,"startSearchRange":{"startDate":"2023-10-24","endDate":"2023-10-27"},"endSearchRange":{"startDate":"2023-10-26","endDate":"2023-10-27"},"start":{"date":"2023-10-26","closedAt":"2023-10-26T15:00:00+08:00","close":"120","tiedDates":["2023-10-26"]},"end":{"date":"2023-10-27","closedAt":"2023-10-27T15:00:00+08:00","close":"119","tiedDates":["2023-10-27"]},"startKnownAt":"2023-10-27T15:00:00+08:00","isEnded":false,"endKnownAt":null,"startValidity":"VALID","endValidity":"VALID","endpointValidity":"VALID","issues":[],"internalPriceRelations":{"highs":[{"date":"2023-10-26","close":"120"}],"lows":[{"date":"2023-10-27","close":"119"}],"highComparisons":[],"lowComparisons":[],"status":"INSUFFICIENT"},"tailReview":{"range":{"startDate":"2023-10-27","endDate":"2023-10-27"},"turnIds":["000001.SH:day:CLOSE:2023-10-27","000001.SH:day:DIF:2023-10-27"],"extrema":{"maxClose":{"value":"119","dates":["2023-10-27"]},"minClose":{"value":"119","dates":["2023-10-27"]},"maxDif":{"value":"6","dates":["2023-10-27"]},"minDif":{"value":"6","dates":["2023-10-27"]},"longestRed":null,"longestGreen":{"value":"-1","absoluteLength":"1","dates":["2023-10-27"]}},"strictlyBrokeStart":false,"touchedStart":false},"extrema":{"maxClose":{"value":"120","dates":["2023-10-26"]},"minClose":{"value":"119","dates":["2023-10-27"]},"maxDif":{"value":"7","dates":["2023-10-26"]},"minDif":{"value":"6","dates":["2023-10-27"]},"longestRed":{"value":"2","absoluteLength":"2","dates":["2023-10-26"]},"longestGreen":{"value":"-1","absoluteLength":"1","dates":["2023-10-27"]}},"difTurnIds":["000001.SH:day:DIF:2023-10-26","000001.SH:day:DIF:2023-10-27"]}]};
export function dailyWaveEndedFixture(): DailyWaveReadyResponse { return structuredClone(literalEnded); }
