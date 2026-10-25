import type { IndexDetailKlineResponseDto } from "../api/indexDetailApiTypes";
import { toCandlePoint } from "../api/indexDetailViewModelAdapter";
import type { IndexCandlePoint } from "../model/indexDetailTypes";
import type {
  DailyWaveColorSegment, DailyWaveConfirmedTurn, DailyWaveDateRange, DailyWaveEmptyResponse,
  DailyWaveExtrema, DailyWavePendingTurn, DailyWavePriceSegment,
  DailyWaveReadyResponse, DailyWaveResponse,
} from "./types";

type Parser<T> = (value: unknown) => T;
export class DailyWaveContractError extends Error {
  constructor() { super("波段划分结果校验失败，请重试"); }
}
const fail = (): never => { throw new DailyWaveContractError(); };
function ensure(condition: unknown): asserts condition { if (!condition) fail(); }
const text: Parser<string> = value => { ensure(typeof value === "string" && value.length > 0); return value; };
const bool: Parser<boolean> = value => { ensure(typeof value === "boolean"); return value; };
const integer: Parser<number> = value => { ensure(typeof value === "number" && Number.isSafeInteger(value)); return value; };
const count: Parser<number> = value => { const result = integer(value); ensure(result >= 0); return result; };
const positiveCount: Parser<number> = value => { const result = count(value); ensure(result > 0); return result; };
function literal<const T extends string | number | null>(...allowed: readonly T[]): Parser<T> {
  return value => { ensure(allowed.some(item => item === value)); return value as T; };
}
function nullable<T>(parse: Parser<T>): Parser<T | null> { return value => value === null ? null : parse(value); }
function array<T>(parse: Parser<T>): Parser<T[]> { return value => { ensure(Array.isArray(value)); return value.map(parse); }; }
function object<S extends Record<string, Parser<unknown>>>(shape: S): Parser<{ [K in keyof S]: ReturnType<S[K]> }> {
  return value => {
    ensure(value !== null && typeof value === "object" && !Array.isArray(value));
    const record = value as Record<string, unknown>;
    const keys = Object.keys(shape);
    ensure(Object.keys(record).length === keys.length && keys.every(key => Object.hasOwn(record, key)));
    return Object.fromEntries(keys.map(key => [key, shape[key]!(record[key])])) as { [K in keyof S]: ReturnType<S[K]> };
  };
}
const day: Parser<string> = value => {
  const result = text(value);
  ensure(/^\d{4}-\d{2}-\d{2}$/.test(result));
  const parsed = new Date(`${result}T00:00:00Z`);
  ensure(Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === result);
  return result;
};
const time: Parser<string> = value => {
  const result = text(value);
  ensure(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?\+08:00$/.test(result));
  day(result.slice(0, 10));
  ensure(Number(result.slice(11, 13)) < 24 && Number(result.slice(14, 16)) < 60
    && Number(result.slice(17, 19)) < 60 && Number.isFinite(Date.parse(result)));
  return result;
};
const closed = (date: string) => `${date}T15:00:00+08:00`;
const closeTime: Parser<string> = value => { const result = time(value); ensure(result === closed(result.slice(0, 10))); return result; };
const decimal: Parser<string> = value => {
  const result = text(value);
  ensure(result !== "-0" && /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]*[1-9])?$/.test(result) && Number.isFinite(Number(result)));
  return result;
};
const positive: Parser<string> = value => { const result = decimal(value); ensure(!result.startsWith("-") && Number(result) > 0); return result; };
// Compare the preserved decimal text without converting contract relationships to rounded floats.
function compare(left: string, right: string): number {
  if (left === right) return 0;
  const negativeLeft = left.startsWith("-"), negativeRight = right.startsWith("-");
  if (negativeLeft !== negativeRight) return negativeLeft ? -1 : 1;
  const [li, lf = ""] = left.replace(/^-/, "").split(".");
  const [ri, rf = ""] = right.replace(/^-/, "").split(".");
  const width = Math.max(lf.length, rf.length);
  const l = `${li}.${lf.padEnd(width, "0")}`, r = `${ri}.${rf.padEnd(width, "0")}`;
  const result = li!.length !== ri!.length ? Math.sign(li!.length - ri!.length) : l < r ? -1 : 1;
  return negativeLeft ? -result : result;
}
const dates = (values: string[], nonempty = true) => {
  ensure((!nonempty || values.length > 0) && values.every((value, i) => i === 0 || values[i - 1]! < value));
};
const unique = (values: readonly unknown[]) => ensure(new Set(values).size === values.length);
const ids = array(text), days = array(day);
const range = object({ startDate: day, endDate: day });
const extreme = object({ value: decimal, dates: days });
const priceExtreme = object({ value: positive, dates: days });
const histogram = object({ value: decimal, dates: days, absoluteLength: positive });
const extrema = object({ maxClose: priceExtreme, minClose: priceExtreme, maxDif: extreme, minDif: extreme,
  longestRed: nullable(histogram), longestGreen: nullable(histogram) });
const turnBase = { id: text, metric: literal("CLOSE", "DIF"), value: decimal, firstDate: day, lastDate: day, plateauDates: days };
const confirmed = object({ ...turnBase, kind: literal("MAX", "MIN"), confirmedAt: closeTime });
const pending = object({ ...turnBase, kind: literal(null), confirmedAt: literal(null), possibleKind: literal("MAX", "MIN", null) });
const color = object({ id: text, color: literal("RED", "GREEN"), startDate: day, endDate: day, lastColoredDate: day,
  coloredCount: positiveCount, zeroDates: days, isLeftComplete: bool, isEnded: bool,
  endKnownAt: nullable(closeTime), turnIds: ids, extrema });
const endpoint = object({ date: day, closedAt: closeTime, close: positive, tiedDates: days });
const issue = object({ message: text, dates: days });
const relation = object({ fromDate: day, toDate: day, relation: literal("HIGHER", "LOWER", "EQUAL") });
const pricePoint = object({ date: day, close: positive });
const internal = object({ highs: array(pricePoint), lows: array(pricePoint), highComparisons: array(relation), lowComparisons: array(relation),
  status: literal("INSUFFICIENT", "RISING", "FALLING", "MIXED", "EQUAL") });
const tail = object({ range: nullable(range), turnIds: ids, extrema: nullable(extrema), strictlyBrokeStart: nullable(bool), touchedStart: nullable(bool) });
const validity = literal("VALID", "INVALID", "UNKNOWN");
const price = object({ id: text, sourceColorSegmentId: text, previousColorSegmentId: nullable(text), direction: literal("UP", "DOWN"),
  generated: bool, startSearchRange: nullable(range), endSearchRange: nullable(range), start: nullable(endpoint), end: nullable(endpoint),
  startKnownAt: nullable(closeTime), isEnded: bool, endKnownAt: nullable(closeTime), startValidity: validity, endValidity: validity,
  endpointValidity: validity, issues: array(issue), internalPriceRelations: nullable(internal), tailReview: tail, extrema: nullable(extrema), difTurnIds: ids });
const mapping = object({ sourceColorSegmentId: text, priceSegmentId: text, colorRange: range, priceRange: nullable(range),
  observationIntersection: nullable(range), priceObservationIntersection: nullable(range), sourceTurnIds: ids, priceTurnIds: ids,
  endpointOffsets: array(object({ difTurnId: text, priceEndpoint: literal("START", "END"), tradingDayOffset: integer })), issues: array(issue) });
const barStats = object({ coloredCount: positiveCount, longestBar: histogram });
const tripleBars = object({ previous: barStats, opposite: barStats, next: barStats });
const triplePrices = object({ previous: priceExtreme, opposite: priceExtreme, next: priceExtreme });
const shortOpposite = object({ previousColorSegmentId: text, oppositeColorSegmentId: text, nextColorSegmentId: text,
  barStats: tripleBars, priceHighs: triplePrices, priceLows: triplePrices, difTurnIds: ids });
const coverage = object({ mainPointCount: count, leftIncompleteColorSegmentIds: ids, ungeneratedPriceSegmentIds: ids,
  invalidPriceSegmentIds: ids, unknownPriceSegmentIds: ids,
  counts: object({ leftIncomplete: count, ungenerated: count, invalid: count, unknown: count }) });
const header = { schemaVersion: literal(1), tsCode: literal("000001.SH"), period: literal("day"),
  ruleId: literal("xxm-daily-wave-review-v0.1"), calculationId: text, calculatedAt: time,
  requestedStart: literal("2023-10-24"), requestedEnd: literal("2026-10-21") };
const parseEmpty: Parser<DailyWaveEmptyResponse> = object({ ...header, status: literal("empty") });
const parseReady: Parser<DailyWaveReadyResponse> = object({ ...header, status: literal("ready"), observationStart: day,
  observationEnd: day, contextStart: day, contextEnd: day, asOf: closeTime,
  sourcePoints: array(object({ date: day, close: positive, dif: decimal, dea: decimal, macd: decimal })),
  turns: array(confirmed), pendingTurns: array(pending), colorSegments: array(color), segments: array(price),
  mappings: array(mapping), shortOppositeSegments: array(shortOpposite), coverage });

function checkRange(value: DailyWaveDateRange | null) { if (value) ensure(value.startDate <= value.endDate); }
function checkExtrema(value: DailyWaveExtrema | null) {
  if (!value) return;
  [value.maxClose, value.minClose, value.maxDif, value.minDif, value.longestRed, value.longestGreen]
    .forEach(item => { if (item) dates(item.dates); });
  ensure(compare(value.minClose.value, value.maxClose.value) <= 0 && compare(value.minDif.value, value.maxDif.value) <= 0);
  for (const [item, negative] of [[value.longestRed, false], [value.longestGreen, true]] as const) {
    if (item) ensure(item.value !== "0" && item.value.startsWith("-") === negative && item.value.replace(/^-/, "") === item.absoluteLength);
  }
}
function checkTurn(turn: DailyWaveConfirmedTurn | DailyWavePendingTurn) {
  dates(turn.plateauDates);
  ensure(turn.firstDate === turn.plateauDates[0] && turn.lastDate === turn.plateauDates.at(-1)
    && turn.id === `000001.SH:day:${turn.metric}:${turn.firstDate}`);
  if (turn.confirmedAt !== null) ensure(turn.confirmedAt > closed(turn.lastDate));
}
function checkColor(item: DailyWaveColorSegment) {
  dates(item.zeroDates, false); unique(item.turnIds); checkExtrema(item.extrema);
  ensure(item.startDate <= item.lastColoredDate && item.lastColoredDate <= item.endDate
    && item.zeroDates.every(date => item.startDate <= date && date <= item.endDate)
    && !item.zeroDates.includes(item.lastColoredDate)
    && item.id === `000001.SH:day:${item.color}:${item.startDate}`
    && item.isEnded === (item.endKnownAt !== null)
    && (item.endKnownAt === null || item.endKnownAt > closed(item.endDate)));
}
function checkPrice(item: DailyWavePriceSegment) {
  checkRange(item.startSearchRange); checkRange(item.endSearchRange); checkRange(item.tailReview.range);
  checkExtrema(item.extrema); checkExtrema(item.tailReview.extrema);
  ensure(item.id === `${item.sourceColorSegmentId}:PRICE:${item.direction}`);
  unique(item.difTurnIds); unique(item.tailReview.turnIds);
  for (const endpoint of [item.start, item.end]) {
    if (endpoint) { dates(endpoint.tiedDates); ensure(endpoint.date === endpoint.tiedDates[0] && endpoint.closedAt === closed(endpoint.date)); }
  }
  if (!item.generated) {
    ensure([item.start, item.end, item.startKnownAt, item.endKnownAt, item.extrema, item.internalPriceRelations,
      item.tailReview.range, item.tailReview.extrema, item.tailReview.strictlyBrokeStart, item.tailReview.touchedStart].every(value => value === null)
      && !item.isEnded && !item.difTurnIds.length && !item.tailReview.turnIds.length && item.issues.length > 0
      && [item.startValidity, item.endValidity, item.endpointValidity].every(value => value === "UNKNOWN"));
  } else {
    ensure([item.start, item.end, item.startKnownAt, item.startSearchRange, item.endSearchRange, item.extrema,
      item.internalPriceRelations, item.tailReview.range, item.tailReview.extrema,
      item.tailReview.strictlyBrokeStart, item.tailReview.touchedStart].every(value => value !== null)
      && item.isEnded === (item.endKnownAt !== null));
  }
  const relations = item.internalPriceRelations;
  if (relations) {
    for (const [points, comparisons] of [[relations.highs, relations.highComparisons], [relations.lows, relations.lowComparisons]] as const) {
      dates(points.map(point => point.date), false);
      ensure(comparisons.length === Math.max(0, points.length - 1));
      comparisons.forEach((comparison, i) => ensure(comparison.fromDate === points[i]!.date && comparison.toDate === points[i + 1]!.date));
    }
    ensure((relations.highs.length < 2 || relations.lows.length < 2) === (relations.status === "INSUFFICIENT"));
  }
}
const same = (left: unknown, right: unknown) => JSON.stringify(left) === JSON.stringify(right);
function checkMappings(response: DailyWaveReadyResponse,
  colors: Map<string, DailyWaveColorSegment>, prices: Map<string, DailyWavePriceSegment>,
  turns: Map<string, DailyWaveConfirmedTurn | DailyWavePendingTurn>) {
  const intersection = (start: string, end: string): DailyWaveDateRange | null => {
    const startDate = start > response.observationStart ? start : response.observationStart;
    const endDate = end < response.observationEnd ? end : response.observationEnd;
    return startDate <= endDate ? { startDate, endDate } : null;
  };
  ensure(response.mappings.length === prices.size); unique(response.mappings.map(item => item.priceSegmentId));
  for (const mapping of response.mappings) {
    checkRange(mapping.colorRange); checkRange(mapping.priceRange); checkRange(mapping.observationIntersection); checkRange(mapping.priceObservationIntersection);
    unique(mapping.priceTurnIds); unique(mapping.endpointOffsets.map(offset => `${offset.difTurnId}|${offset.priceEndpoint}`));
    const color = colors.get(mapping.sourceColorSegmentId), price = prices.get(mapping.priceSegmentId);
    ensure(color && price && price.sourceColorSegmentId === mapping.sourceColorSegmentId
      && [...mapping.sourceTurnIds, ...mapping.priceTurnIds].every(id => turns.has(id))
      && mapping.endpointOffsets.every(offset => turns.get(offset.difTurnId)?.metric === "DIF")
      && mapping.colorRange.startDate === color.startDate && mapping.colorRange.endDate === color.endDate
      && same(mapping.sourceTurnIds, color.turnIds)
      && same(mapping.observationIntersection, intersection(color.startDate, color.endDate)));
    if (price.generated) {
      ensure(price.start && price.end && mapping.priceRange?.startDate === price.start.date
        && mapping.priceRange?.endDate === price.end.date
        && same(mapping.priceObservationIntersection, intersection(price.start.date, price.end.date)));
    } else ensure(mapping.priceRange === null && mapping.priceObservationIntersection === null
      && mapping.priceTurnIds.length === 0 && mapping.endpointOffsets.length === 0);
  }
}
function checkReady(response: DailyWaveReadyResponse) {
  const days = response.sourcePoints.map(point => point.date); dates(days);
  ensure(days.length <= 800 && response.observationStart === days[0] && response.observationEnd === days.at(-1)
    && response.contextEnd === response.observationEnd && "2021-10-01" <= response.contextStart && response.contextStart <= response.observationStart
    && response.requestedStart <= response.observationStart && response.observationStart <= response.observationEnd
    && response.observationEnd <= response.requestedEnd && response.asOf === closed(response.observationEnd)
    && response.calculatedAt >= response.asOf && response.coverage.mainPointCount === days.length);
  const turnList = [...response.turns, ...response.pendingTurns];
  const turns = new Map(turnList.map(item => [item.id, item]));
  const colors = new Map(response.colorSegments.map(item => [item.id, item]));
  const prices = new Map(response.segments.map(item => [item.id, item]));
  ensure(turns.size === turnList.length && colors.size === response.colorSegments.length && prices.size === response.segments.length);
  for (const turn of turns.values()) {
    checkTurn(turn); ensure(response.contextStart <= turn.firstDate && turn.lastDate <= response.contextEnd
      && (turn.confirmedAt === null || turn.confirmedAt <= response.asOf));
  }
  for (const color of colors.values()) {
    checkColor(color); ensure(response.contextStart <= color.startDate && color.endDate <= response.contextEnd
      && (color.endKnownAt === null || color.endKnownAt <= response.asOf) && color.turnIds.every(id => turns.has(id)));
  }
  for (const item of prices.values()) {
    checkPrice(item);
    const color = colors.get(item.sourceColorSegmentId);
    ensure(color && (item.previousColorSegmentId === null || colors.has(item.previousColorSegmentId))
      && [...item.difTurnIds, ...item.tailReview.turnIds].every(id => turns.has(id))
      && item.difTurnIds.every(id => turns.get(id)?.metric === "DIF") && item.direction === (color.color === "RED" ? "UP" : "DOWN"));
    if (item.generated) {
      ensure(item.start && item.end && item.startSearchRange && item.endSearchRange && item.tailReview.range
        && item.startKnownAt === closed(color.startDate) && item.isEnded === color.isEnded && item.endKnownAt === color.endKnownAt);
      for (const [endpoint, search] of [[item.start, item.startSearchRange], [item.end, item.endSearchRange]] as const) {
        ensure(response.contextStart <= search.startDate && search.endDate <= color.endDate
          && endpoint.tiedDates.every(date => search.startDate <= date && date <= search.endDate));
      }
      ensure(item.endSearchRange.startDate === item.start.date && item.endSearchRange.endDate === color.endDate
        && item.tailReview.range.startDate === item.end.date && item.tailReview.range.endDate === color.endDate);
    }
  }
  checkMappings(response, colors, prices, turns);
  for (const triple of response.shortOppositeSegments) {
    unique(triple.difTurnIds);
    ensure([triple.previousColorSegmentId, triple.oppositeColorSegmentId, triple.nextColorSegmentId].every(id => colors.has(id))
      && triple.difTurnIds.every(id => turns.get(id)?.metric === "DIF"));
    for (const bar of Object.values(triple.barStats)) {
      dates(bar.longestBar.dates); ensure(bar.longestBar.value.replace(/^-/, "") === bar.longestBar.absoluteLength);
    }
    [...Object.values(triple.priceHighs), ...Object.values(triple.priceLows)].forEach(item => dates(item.dates));
  }
  const expected = [response.colorSegments.filter(item => !item.isLeftComplete && item.startDate <= response.observationEnd
    && item.endDate >= response.observationStart).map(item => item.id), response.segments.filter(item => !item.generated).map(item => item.id),
  response.segments.filter(item => item.endpointValidity === "INVALID").map(item => item.id), response.segments.filter(item => item.endpointValidity === "UNKNOWN").map(item => item.id)];
  const coverage = response.coverage;
  ensure(same(expected, [coverage.leftIncompleteColorSegmentIds, coverage.ungeneratedPriceSegmentIds, coverage.invalidPriceSegmentIds, coverage.unknownPriceSegmentIds])
    && same(expected.map(ids => ids.length), [coverage.counts.leftIncomplete, coverage.counts.ungenerated, coverage.counts.invalid, coverage.counts.unknown]));
}

export function decodeDailyWaveResponse(raw: unknown): DailyWaveResponse {
  ensure(raw !== null && typeof raw === "object" && "status" in raw);
  if (raw.status === "empty") return parseEmpty(raw);
  const response = parseReady(raw);
  checkReady(response);
  return response;
}

export type DailyWaveKlineMatch = { matched: true; candles: IndexCandlePoint[] } | { matched: false; message: string };
export function matchDailyWaveKline(response: DailyWaveReadyResponse, kline: IndexDetailKlineResponseDto): DailyWaveKlineMatch {
  const mismatch: DailyWaveKlineMatch = { matched: false, message: "行情与研究结果不一致，暂不显示波段" };
  if (kline?.indexRef?.tsCode !== response.tsCode || kline?.period !== "day" || !Array.isArray(kline.bars)
      || kline.bars.length !== response.sourcePoints.length) return mismatch;
  for (let i = 0; i < kline.bars.length; i++) {
    const bar = kline.bars[i], source = response.sourcePoints[i];
    if (!bar || !source || bar.tradeDate !== source.date || i > 0 && kline.bars[i - 1]!.tradeDate >= bar.tradeDate) return mismatch;
    const actual = [bar.close, bar.factors?.macd?.dif, bar.factors?.macd?.dea, bar.factors?.macd?.macd];
    const expected = [source.close, source.dif, source.dea, source.macd].map(Number);
    if (!actual.every((value, index) => typeof value === "number" && Number.isFinite(value)
        && Number.isFinite(expected[index]) && value === expected[index])) return mismatch;
  }
  return { matched: true, candles: kline.bars.map(toCandlePoint) };
}
