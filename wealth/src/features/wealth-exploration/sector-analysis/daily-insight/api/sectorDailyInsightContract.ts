// Transport validation only. Selection, ordering and evidence are backend facts.
type Reader<T> = (value: unknown) => T;
type Shape = Record<string, Reader<unknown>>;
type ReadShape<S extends Shape> = { [K in keyof S]: ReturnType<S[K]> };

export class DailyInsightContractError extends Error {
  constructor() { super("每日洞察数据格式不符合约定，请稍后重试。"); }
}
function fail(): never { throw new DailyInsightContractError(); }
function object<S extends Shape>(shape: S): Reader<ReadShape<S>> {
  return (value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return fail();
    const source = value as Record<string, unknown>;
    if (Object.keys(source).length !== Object.keys(shape).length || Object.keys(source).some((key) => !(key in shape))) return fail();
    return Object.fromEntries(Object.entries(shape).map(([key, read]) => [key, read(source[key])])) as ReadShape<S>;
  };
}
function choices<const T extends readonly (string | number)[]>(values: T): Reader<T[number]> {
  return (value) => values.includes(value as T[number]) ? value as T[number] : fail();
}
function nullable<T>(read: Reader<T>): Reader<T | null> { return (value) => value === null ? null : read(value); }
function array<T>(read: Reader<T>): Reader<T[]> { return (value) => Array.isArray(value) ? value.map(read) : fail(); }
const text: Reader<string> = (value) => typeof value === "string" && value.trim() ? value : fail();
const optionalText = nullable((value: unknown) => typeof value === "string" ? value : fail());
const finite: Reader<number> = (value) => typeof value === "number" && Number.isFinite(value) ? value : fail();
const count: Reader<number> = (value) => Number.isSafeInteger(finite(value)) && (value as number) >= 0 ? value as number : fail();
const positive: Reader<number> = (value) => count(value) > 0 ? value as number : fail();
const integer: Reader<number> = (value) => Number.isSafeInteger(finite(value)) ? value as number : fail();
const percent: Reader<number> = (value) => finite(value) >= 0 && (value as number) <= 100 ? value as number : fail();
const boolean: Reader<boolean> = (value) => typeof value === "boolean" ? value : fail();
export function isDailyInsightDate(value: string): boolean {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value)) && new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) === value;
}
const date: Reader<string> = (value) => isDailyInsightDate(text(value)) ? value as string : fail();
const timestamp: Reader<string> = (value) => /T/.test(text(value)) && Number.isFinite(Date.parse(value as string)) ? value as string : fail();
const uuid: Reader<string> = (value) => /^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(text(value)) ? value as string : fail();
const code: Reader<string> = (value) => /^BK[0-9]{4}\.DC$/.test(text(value)) ? value as string : fail();
const level = choices([1, 2, 3]);
export const DAILY_EVIDENCE = ["PRICE_VOLUME", "MEMBER_BREADTH", "TURNOVER_BREADTH", "DUAL_MOMENTUM", "RELATIVE_ROTATION", "MA20_BREADTH"] as const;
export const DAILY_EVENTS = ["HEAD_GAINER", "HEAD_LOSER", "STRENGTHENING", "WEAKENING", "COUNTER_TREND_STRENGTHENING", "RISING_BUT_WEAKENING"] as const;
export const DAILY_REASON_FIELDS = {
  HISTORY: "missingHistoryCount", DATE: "missingDateCount", PRICE: "missingPriceCount", MEMBER: "missingMemberCount",
  AMOUNT: "missingAmountCount", ADJ_FACTOR: "missingAdjFactorCount", GROUP_SIZE: "missingGroupSizeCount",
  COVERAGE: "missingCoverageCount", PREVIOUS_BATCH: "missingPreviousBatchCount", OTHER: "missingOtherCount",
} as const;
const coverage = object({ tradeDate: date, availability: choices(["PUBLISHED", "MISSING"]), batchKey: nullable(uuid), hierarchyVersion: nullable(text), publishedAt: nullable(timestamp) });
const readMeta = object({
  status: choices(["READY", "DELAYED", "EMPTY", "ERROR"]), message: optionalText, exceptionCode: optionalText,
  contractKey: choices(["sector-daily-insight"]), contractVersion: choices([1]), formulaBundleVersion: text, templateVersion: text,
  levels: array(level), defaultLevel: choices([1]),
  dateContext: object({ requestedTradeDate: date, observedTradeDate: nullable(date), previousTradeDate: nullable(date), mode: choices(["AUTO"]), isDelayed: boolean, asOf: timestamp, delayReason: optionalText }),
  coverageStartDate: date, coverageEndDate: date, tradeDates: array(coverage), defaultTradeDate: nullable(date), defaultBatchKey: nullable(uuid), hierarchyVersion: nullable(text),
});
const readSummary = object({
  sectorCount: count, calculableCount: count, missingCount: count, upCount: count, downCount: count, flatCount: count,
  medianChangePct1d: nullable(finite), dualMomentumCount20d80: count, leadingImprovingCount20d5d: count, priceVolumeJointCount20d: count, breadthUpShareAbove50Count: count,
  missingHistoryCount: count, missingDateCount: count, missingPriceCount: count, missingMemberCount: count, missingAmountCount: count,
  missingAdjFactorCount: count, missingGroupSizeCount: count, missingCoverageCount: count, missingPreviousBatchCount: count, missingOtherCount: count,
});
const priceVolume = nullable(choices(["JOINT", "PRICE_ONLY", "AMOUNT_ONLY", "NEUTRAL"]));
const dual = nullable(choices(["QUALIFIED", "NOT_QUALIFIED", "NOT_EVALUATED"]));
const rotation = nullable(choices(["LEADING_IMPROVING", "WEAK_IMPROVING", "STRONG_NOT_IMPROVING", "WEAK_NOT_IMPROVING", "SAMPLE_INSUFFICIENT", "DATA_INSUFFICIENT"]));
const readItem = object({
  sectorCode: code, sectorName: text, hierarchyPath: text, industryLevel: level, eventType: choices(DAILY_EVENTS),
  returnPct1d: nullable(finite), returnPct5d: nullable(finite), returnPct20d: nullable(finite),
  currentRank20d: nullable(positive), currentRankableCount20d: nullable(count), currentPercentile20d: nullable(percent),
  previousRank20d: nullable(positive), previousRankableCount20d: nullable(count), previousPercentile20d: nullable(percent),
  rankChange: nullable(integer), percentileChangePp: nullable(finite),
  priceVolumeStateCurrent: priceVolume, priceVolumeStatePrevious: priceVolume,
  dualQualification20d80Current: dual, dualQualification20d80Previous: dual,
  rotationStatus20dCurrent: rotation, rotationStatus20dPrevious: rotation,
  memberUpPctCurrent: nullable(percent), memberUpPctPrevious: nullable(percent), turnoverUpPctCurrent: nullable(percent), turnoverUpPctPrevious: nullable(percent),
  ma20AbovePctCurrent: nullable(percent), ma20AbovePctPrevious: nullable(percent),
  primaryEvidenceType: nullable(choices(DAILY_EVIDENCE)), secondaryEvidenceTypes: array(choices(DAILY_EVIDENCE)),
  templateKey: choices(["sector-daily-insight"]), templateVersion: text, renderedText: text,
});
const readSnapshot = object({
  status: choices(["READY", "EMPTY", "ERROR"]), message: optionalText, exceptionCode: optionalText,
  requestedTradeDate: date, observedTradeDate: date, previousTradeDate: nullable(date), batchKey: uuid, hierarchyVersion: text,
  formulaBundleVersion: text, templateVersion: text, publishedAt: timestamp, calculatedAt: timestamp, industryLevel: level,
  summary: readSummary, headGainers: array(readItem), headLosers: array(readItem), strengthening: array(readItem), weakening: array(readItem),
  missingSectorCount: count, missingReasonCounts: array(object({ reasonCode: choices(Object.keys(DAILY_REASON_FIELDS) as Array<keyof typeof DAILY_REASON_FIELDS>), count })),
});

export type DailyInsightMeta = ReturnType<typeof readMeta>;
export type DailyInsightSnapshot = ReturnType<typeof readSnapshot>;
export type DailyInsightItem = ReturnType<typeof readItem>;

export function parseDailyInsightMeta(payload: unknown): DailyInsightMeta {
  const meta = readMeta(payload);
  if (meta.levels.join() !== "1,2,3" || meta.coverageStartDate > meta.coverageEndDate || meta.dateContext.requestedTradeDate !== meta.coverageEndDate) fail();
  const dates = meta.tradeDates;
  dates.forEach((day, index) => {
    if (day.tradeDate < meta.coverageStartDate || day.tradeDate > meta.coverageEndDate || (index > 0 && dates[index - 1].tradeDate >= day.tradeDate)) fail();
    if (day.availability === "PUBLISHED" ? !(day.batchKey && day.hierarchyVersion && day.publishedAt) : day.batchKey !== null || day.hierarchyVersion !== null || day.publishedAt !== null) fail();
  });
  const latest = dates.filter((day) => day.availability === "PUBLISHED").at(-1);
  if (meta.dateContext.observedTradeDate !== meta.defaultTradeDate) fail();
  if (!latest) {
    if (meta.defaultTradeDate !== null || meta.defaultBatchKey !== null || meta.hierarchyVersion !== null || meta.status !== "EMPTY" || meta.dateContext.isDelayed) fail();
  } else if (latest.tradeDate !== meta.defaultTradeDate || latest.batchKey !== meta.defaultBatchKey || latest.hierarchyVersion !== meta.hierarchyVersion || meta.status !== (latest.tradeDate < meta.coverageEndDate ? "DELAYED" : "READY") || meta.dateContext.isDelayed !== (meta.status === "DELAYED")) fail();
  return meta;
}

export interface DailyInsightSnapshotRequest {
  tradeDate: string; industryLevel: 1 | 2 | 3; batchKey: string; hierarchyVersion: string;
}
export function parseDailyInsightSnapshot(payload: unknown, request: DailyInsightSnapshotRequest): DailyInsightSnapshot {
  const data = readSnapshot(payload);
  if (data.requestedTradeDate !== request.tradeDate || data.observedTradeDate !== request.tradeDate || data.industryLevel !== request.industryLevel || data.batchKey !== request.batchKey || data.hierarchyVersion !== request.hierarchyVersion) fail();
  if (data.previousTradeDate !== null && data.previousTradeDate >= data.observedTradeDate) fail();
  const s = data.summary;
  if (s.sectorCount !== s.calculableCount + s.missingCount || s.calculableCount !== s.upCount + s.downCount + s.flatCount || data.missingSectorCount !== s.missingCount || data.headGainers.length !== s.upCount || data.headLosers.length !== s.downCount || (s.medianChangePct1d === null) !== (s.calculableCount === 0)) fail();
  if (Object.entries(s).some(([key, value]) => key !== "medianChangePct1d" && (value ?? 0) > s.sectorCount)) fail();
  const expectedReasons = Object.entries(DAILY_REASON_FIELDS).filter(([, field]) => s[field] > 0).map(([reasonCode, field]) => ({ reasonCode, count: s[field] }));
  if (JSON.stringify(data.missingReasonCounts) !== JSON.stringify(expectedReasons)) fail();
  const panels = [data.headGainers, data.headLosers, data.strengthening, data.weakening];
  const events = [["HEAD_GAINER"], ["HEAD_LOSER"], ["STRENGTHENING", "COUNTER_TREND_STRENGTHENING"], ["WEAKENING", "RISING_BUT_WEAKENING"]];
  panels.forEach((rows, index) => {
    if (new Set(rows.map((row) => row.sectorCode)).size !== rows.length || rows.length > s.sectorCount) fail();
    rows.forEach((row) => {
      if (row.industryLevel !== data.industryLevel || row.templateVersion !== data.templateVersion || !events[index].includes(row.eventType)) fail();
      const evidence = row.primaryEvidenceType ? [row.primaryEvidenceType, ...row.secondaryEvidenceTypes] : row.secondaryEvidenceTypes;
      if (evidence.length > 2 || (!row.primaryEvidenceType && evidence.length) || new Set(evidence).size !== evidence.length || evidence.some((value, i) => i > 0 && DAILY_EVIDENCE.indexOf(value) <= DAILY_EVIDENCE.indexOf(evidence[i - 1]))) fail();
      for (const prefix of ["current", "previous"] as const) {
        const rank = row[`${prefix}Rank20d`]; const denominator = row[`${prefix}RankableCount20d`]; const percentile = row[`${prefix}Percentile20d`];
        if ((rank === null) !== (percentile === null) || (rank !== null && (denominator === null || rank > denominator)) || (denominator !== null && denominator > s.sectorCount)) fail();
      }
    });
  });
  return data;
}
