import { FORECAST_PERIODS, type ForecastPeriod, type ForecastResponse, type ForecastPriceRange, type ForecastExpression, type ForecastCloseRange, type ForecastReference, type ForecastCondition } from "./types";

const HASH = /^[0-9a-f]{64}$/;
const routes = ["dif_turn", "color_flip"];
const entryReasons = ["PRICE_NOT_EXTREME", "DIF_NOT_DIVERGENT", "WRONG_COLOR_OR_ZERO", "INSUFFICIENT_BARS", "PRECISION_UNRESOLVED"];
const targetReasons = ["CANCEL_BEFORE_TARGET", "EARLY_STRUCTURE", "COLOR_OR_ZERO", "NO_TARGET_SOLUTION", "PRECISION_UNRESOLVED"];
const reasons = ["ZERO_WAVE", "NO_REFERENCE", "NO_ENTRY_RANGE", "NO_CONFIRMATION_IN_HORIZON", "SOURCE_DELAYED", "SOURCE_EMPTY", "CALIBRATION_FAILED", "ROUNDING_BOUNDARY", "NARROW_INTERVAL"];
const rootKeys = new Set(["tsCode", "period", "forecastVersion", "forecastSpecHash", "detectorSpecHash", "sourceInputId", "calendarInputId", "computedThrough", "requestedAsOf", "mode", "dataStatus", "ordinaryState", "direction", "status", "reasonCode", "precisionPolicy", "forecastId", "targetEndpoint", "barsAhead", "activation", "assumption", "targetEntryRanges", "targetEntryExclusions", "relations", "commonConditions", "examples", "applicabilityText", "invalidationText", "confirmedAt", "confirmedDirection", "display", "refreshAfterMs"]);
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
function range(r: ForecastPriceRange): boolean {
  return !!r && (r.lower === null || finite(r.lower) && r.lower >= 0) && (r.upper === null || finite(r.upper) && r.upper > 0)
    && typeof r.lowerInclusive === "boolean" && typeof r.upperInclusive === "boolean"
    && !(r.lower === null && r.lowerInclusive) && !(r.lower === 0 && r.lowerInclusive) && !(r.upper === null && r.upperInclusive)
    && (r.lower === null || r.upper === null || r.lower < r.upper || r.lower === r.upper && r.lowerInclusive && r.upperInclusive);
}
function reference(r: ForecastReference): boolean {
  return !!r && typeof r.startTime === "string" && typeof r.endTime === "string" && finite(r.price) && r.price > 0 && finite(r.dif);
}
function expression(e: ForecastExpression): boolean {
  if (!e || typeof e !== "object") return false;
  switch (e.op) {
    case "affine": return finite(e.constant) && finite(e.pCoefficient) && finite(e.cCoefficient);
    case "abs": return expression(e.arg);
    case "scale": return finite(e.factor) && expression(e.arg);
    case "round3": return finite(e.guard) && e.guard > 0 && e.arg?.op === "affine" && expression(e.arg);
    case "sub": return Array.isArray(e.args) && e.args.length === 2 && e.args.every(expression);
    default: return false;
  }
}
function condition(c: ForecastCondition): boolean {
  return !!c && ["lt", "le", "eq", "ge", "gt"].includes(c.op) && expression(c.left) && expression(c.right);
}
function closeRange(r: ForecastCloseRange): boolean {
  return range(r) && routes.includes(r.route) && [2, 4].includes(r.displayPlaces) && finite(r.displayLower) && r.displayLower > 0
    && (r.lower === null || r.displayLower > r.lower || r.displayLower === r.lower && r.lowerInclusive)
    && (r.upper === null ? r.displayUpper === null : finite(r.displayUpper) && r.displayUpper >= r.displayLower
      && (r.displayUpper < r.upper || r.displayUpper === r.upper && r.upperInclusive));
}

export function adaptForecast(value: ForecastResponse, period: ForecastPeriod, asOf?: string): ForecastResponse {
  const fail = () => { throw new Error("预判响应与当前周期不一致，请重试"); };
  if (!value || Object.keys(value).some(k => !rootKeys.has(k)) || value.tsCode !== "000001.SH" || value.period !== period
    || !FORECAST_PERIODS.includes(value.period) || value.forecastVersion !== "xxm-key-point-forecast-v0.2"
    || value.requestedAsOf !== (asOf ?? null) || value.mode !== (asOf ? "REPLAY" : "LATEST")
    || !["READY", "CONDITIONAL_ENTRY", "ENTRY_ONLY", "NO_CANDIDATE", "CONFIRMED", "PRECISION_PENDING", "DELAYED", "EMPTY"].includes(value.status)
    || !["READY", "DELAYED", "EMPTY"].includes(value.dataStatus)
    || (value.ordinaryState !== null && !["NONE", "DULL", "STRUCTURE"].includes(value.ordinaryState))
    || (value.direction !== null && !["TOP", "BOTTOM"].includes(value.direction))
    || (value.reasonCode !== null && !reasons.includes(value.reasonCode))
    || value.precisionPolicy !== (period === "day" ? "rounded3_guarded" : "full_float")
    || !HASH.test(value.forecastId) || !HASH.test(value.forecastSpecHash) || !HASH.test(value.detectorSpecHash)
    || (value.sourceInputId !== null && !HASH.test(value.sourceInputId)) || (value.calendarInputId !== null && !HASH.test(value.calendarInputId))
    || !finite(value.refreshAfterMs) || value.refreshAfterMs <= 0
    || !value.display || Object.values(value.display).some(v => typeof v !== "string")
    || typeof value.applicabilityText !== "string" || typeof value.invalidationText !== "string"
    || ![value.relations, value.targetEntryRanges, value.targetEntryExclusions, value.commonConditions, value.examples].every(Array.isArray)) fail();
  const successful = value.status === "READY" || value.status === "CONDITIONAL_ENTRY";
  if (value.targetEndpoint !== null && (!value.computedThrough || value.targetEndpoint <= value.computedThrough || !value.barsAhead
    || !Number.isInteger(value.barsAhead) || value.barsAhead > 20 || !["READY", "CONDITIONAL_ENTRY", "PRECISION_PENDING"].includes(value.status))) fail();
  if (value.targetEndpoint === null && value.barsAhead !== null) fail();
  if (successful && (value.dataStatus !== "READY" || !value.targetEndpoint || !value.sourceInputId || !value.calendarInputId || !value.relations.length || !value.assumption)) fail();
  if (!successful && (value.relations.length || value.commonConditions.length || value.examples.length || value.assumption)) fail();
  if (value.status === "READY" && (value.ordinaryState !== "DULL" || value.activation !== null || value.targetEntryRanges.length)) fail();
  if (value.status === "CONFIRMED" && (!value.confirmedAt || !value.confirmedDirection)) fail();
  if (["DELAYED", "EMPTY", "CONFIRMED"].includes(value.status) && value.activation !== null) fail();
  const ids = new Set<string>();
  if (value.activation) {
    if (!value.computedThrough || value.activation.endpoint <= value.computedThrough || !Array.isArray(value.activation.ranges) || !Array.isArray(value.activation.exclusions)) fail();
    for (const r of value.activation.ranges) {
      if (!r.entryRangeId || ids.has(r.entryRangeId) || !range(r.priceRange) || !reference(r.reference)) fail();
      ids.add(r.entryRangeId);
    }
    if (new Set(value.activation.ranges.map(r => r.reference.startTime)).size > 2) fail();
    for (const e of value.activation.exclusions) if (!range(e.priceRange) || !entryReasons.includes(e.reason)) fail();
  }
  if (["CONDITIONAL_ENTRY", "ENTRY_ONLY"].includes(value.status) && (value.ordinaryState !== "NONE" || !value.activation?.ranges.length)) fail();
  if (value.status === "CONDITIONAL_ENTRY" && (!value.targetEntryRanges.length || !value.barsAhead || value.barsAhead < 2)) fail();
  const contains = (r: ForecastPriceRange, p: number) => (r.lower === null || p > r.lower || p === r.lower && r.lowerInclusive) && (r.upper === null || p < r.upper || p === r.upper && r.upperInclusive);
  const validIds = (keys: string[]) => Array.isArray(keys) && keys.every(key => ids.has(key));
  for (const r of value.targetEntryRanges) if (!r.entryRangeIds.length || !validIds(r.entryRangeIds) || !range(r.priceRange)) fail();
  for (const e of value.targetEntryExclusions) if (!e.entryRangeIds.length || !validIds(e.entryRangeIds) || !range(e.priceRange) || !targetReasons.includes(e.reason)) fail();
  const relationIds = new Set<string>();
  for (const r of value.relations) {
    if (!r.relationId || relationIds.has(r.relationId) || !validIds(r.entryRangeIds) || !reference(r.reference) || !routes.includes(r.route)
      || (r.entryDomain !== null && !range(r.entryDomain)) || !Array.isArray(r.prefixConditions) || !Array.isArray(r.targetConditions)
      || !r.targetConditions.length || !r.prefixConditions.every(condition) || !r.targetConditions.every(condition)
      || value.status === "CONDITIONAL_ENTRY" && (!r.entryRangeIds.length || r.entryDomain === null)) fail();
    relationIds.add(r.relationId);
  }
  for (const c of value.commonConditions) if (!validIds(c.entryRangeIds) || !reference(c.reference) || !routes.includes(c.route)
    || (c.entryDomain !== null && !range(c.entryDomain)) || !c.closeRanges.length || !c.closeRanges.every(r => closeRange(r) && r.route === c.route)) fail();
  if (value.examples.length > 3) fail();
  for (const e of value.examples) if (!ids.has(e.entryRangeId) || !finite(e.preClose) || e.preClose <= 0 || !value.targetEntryRanges.some(r => r.entryRangeIds.includes(e.entryRangeId) && contains(r.priceRange, e.preClose)) || !e.closeRanges.length || !e.closeRanges.every(closeRange)) fail();
  if (value.assumption) {
    const a = value.assumption;
    if (a.intermediateCloseExpression.op !== "affine" || a.intermediateCloseExpression.cCoefficient !== 0
      || a.intermediateEndpoints.length !== value.barsAhead! - 1
      || value.status === "CONDITIONAL_ENTRY" && (a.activationEndpoint !== value.activation!.endpoint || a.intermediateCloseExpression.pCoefficient !== 1 || a.intermediateCloseExpression.constant !== 0 || value.targetEndpoint! <= a.activationEndpoint!)
      || value.status === "READY" && (a.activationEndpoint !== null || a.intermediateCloseExpression.pCoefficient !== 0 || a.intermediateCloseExpression.constant <= 0)) fail();
    if (a.policy !== "entry_range_then_flat" || !expression(a.intermediateCloseExpression) || !Array.isArray(a.intermediateEndpoints)
      || a.intermediateEndpoints.some((t, i, all) => typeof t !== "string" || t <= value.computedThrough! || t >= value.targetEndpoint! || i > 0 && t <= all[i - 1])) fail();
  }
  return value;
}
