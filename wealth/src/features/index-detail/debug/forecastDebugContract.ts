import { assert, finite, keys, record, timeKey } from "../xxm/adapter";
import { reference, wave } from "./xxmDebugContract";
import type { DecodeForecastDebug } from "./types";
import type { ForecastDebugData, ForecastExpression, ForecastPriceRange } from "../xxm-forecast/types";
export function validateExpression(raw: unknown, bindings: Set<string>, check: () => void, ancestors = new Set<object>()): asserts raw is ForecastExpression {
    check();
    assert(record(raw) && !ancestors.has(raw));
    ancestors.add(raw);
    if (raw.op === "affine") {
        keys(raw, "op pCoefficient cCoefficient constant");
        assert(raw.pCoefficient === 0 && (raw.cCoefficient === 0 || raw.cCoefficient === 1) && finite(raw.constant) && (raw.cCoefficient === 0 || raw.constant === 0));
    }
    else if (raw.op === "macd") {
        keys(raw, "op e12 e26 dea field");
        assert([raw.e12, raw.e26, raw.dea].every(finite) && ["dif", "hist"].includes(String(raw.field)));
        bindings.add(JSON.stringify([raw.e12, raw.e26, raw.dea]));
    }
    else if (raw.op === "sub") {
        keys(raw, "op args");
        assert(Array.isArray(raw.args) && raw.args.length === 2);
        for (const arg of raw.args)
            validateExpression(arg, bindings, check, ancestors);
    }
    else if (raw.op === "scale") {
        keys(raw, "op arg factor");
        assert(finite(raw.factor));
        validateExpression(raw.arg, bindings, check, ancestors);
    }
    else if (raw.op === "abs") {
        keys(raw, "op arg");
        validateExpression(raw.arg, bindings, check, ancestors);
    }
    else if (raw.op === "round3") {
        keys(raw, "op arg guard");
        assert(finite(raw.guard) && raw.guard > 0);
        validateExpression(raw.arg, bindings, check, ancestors);
    }
    else
        assert(false);
    ancestors.delete(raw);
}
function range(raw: unknown, display: boolean): asserts raw is ForecastPriceRange {
    keys(raw, "lower upper lowerInclusive upperInclusive" + (display ? " displayLower displayUpper" : ""));
    assert(finite(raw.lower) && raw.lower >= 0 && (raw.upper === null || finite(raw.upper)) && typeof raw.lowerInclusive === "boolean" && typeof raw.upperInclusive === "boolean");
    assert(raw.lower !== 0 || !raw.lowerInclusive);
    assert(raw.upper !== null || !raw.upperInclusive);
    if (raw.upper !== null)
        assert((raw.upper as number) > raw.lower || raw.upper === raw.lower && raw.lower > 0 && raw.lowerInclusive && raw.upperInclusive);
    if (display) {
        let lo = Math.ceil(raw.lower);
        if (lo === raw.lower && !raw.lowerInclusive)
            lo++;
        let hi = raw.upper === null ? null : Math.floor(raw.upper as number);
        if (hi === raw.upper && !raw.upperInclusive)
            hi!--;
        if (hi !== null && lo > hi)
            assert(raw.displayLower === null && raw.displayUpper === null);
        else
            assert(raw.displayLower === lo && raw.displayUpper === hi && Number.isInteger(lo) && (hi === null || Number.isInteger(hi)));
    }
}
function overlaps(a: ForecastPriceRange, b: ForecastPriceRange) { const lo = Math.max(a.lower, b.lower), hi = Math.min(a.upper ?? Infinity, b.upper ?? Infinity); const contains = (r: ForecastPriceRange) => (lo > r.lower || r.lowerInclusive) && (r.upper === null || lo < r.upper || r.upperInclusive); return lo < hi || lo === hi && contains(a) && contains(b); }
export const decodeForecastDebug: DecodeForecastDebug = (raw, { response, period, check }) => {
    check();
    keys(raw, "sourceInputId calendarInputId precisionPolicy references selectedReference nearestDecision farEvaluated conditions precisionRanges structureFollowConditions");
    assert((raw.sourceInputId === null) === (response.dataStatus === "EMPTY") && (raw.sourceInputId === null || typeof raw.sourceInputId === "string" && !!raw.sourceInputId));
    assert((raw.calendarInputId === null) === (response.targetEndpoint === null) && (raw.calendarInputId === null || typeof raw.calendarInputId === "string" && !!raw.calendarInputId));
    assert(raw.precisionPolicy === (period === "day" ? "rounded3_guarded" : "full_float"));
    keys(raw.references, "nearest farther");
    const through = response.computedThrough;
    for (const r of [raw.references.nearest, raw.references.farther])
        if (r !== null) {
            assert(through);
            reference(r, period, through);
            assert(String((r as {
                endTime: string;
            }).endTime) < through);
        }
    if (raw.references.farther !== null) {
        assert(raw.references.nearest !== null);
        const a = raw.references.farther as {
            endTime: string;
        }, b = raw.references.nearest as {
            startTime: string;
        };
        assert(a.endTime < b.startTime);
    }
    keys(raw.nearestDecision, "status reason");
    assert(["NOT_EVALUATED", "UNAVAILABLE", "HAS_RANGE", "NO_RANGE", "UNCERTAIN"].includes(String(raw.nearestDecision.status)) && (raw.nearestDecision.reason === null || typeof raw.nearestDecision.reason === "string" && !!raw.nearestDecision.reason));
    assert([null, "NEAR", "FAR"].includes(raw.selectedReference as null) && typeof raw.farEvaluated === "boolean" && raw.farEvaluated === (raw.selectedReference === "FAR"));
    if (raw.selectedReference !== null)
        assert(raw.references[raw.selectedReference === "NEAR" ? "nearest" : "farther"] !== null);
    assert(Array.isArray(raw.conditions) && Array.isArray(raw.precisionRanges) && Array.isArray(raw.structureFollowConditions));
    const precision = (values: unknown) => { assert(Array.isArray(values)); for (const p of values) {
        keys(p, "priceRange reason");
        assert(p.reason === "ROUNDING_BOUNDARY");
        range(p.priceRange, false);
    } };
    precision(raw.precisionRanges);
    const bindings = new Set<string>(), ids = new Set<string>(), outcomes = new Set<string>(), directions = new Set<string>();
    const ranges = (values: unknown, pending: unknown) => { assert(Array.isArray(values) && Array.isArray(pending)); let prev: ForecastPriceRange | null = null; for (const r of values) {
        range(r, true);
        assert(!prev || r.lower >= prev.lower && !overlaps(r, prev));
        for (const p of pending) {
            assert(record(p));
            range(p.priceRange, false);
            assert(!overlaps(r, p.priceRange));
        }
        prev = r;
    } };
    const predicates = (values: unknown) => { assert(Array.isArray(values) && values.length > 0); for (const p of values) {
        keys(p, "left op right");
        assert(["lt", "le", "eq", "ge", "gt"].includes(String(p.op)));
        validateExpression(p.left, bindings, check);
        validateExpression(p.right, bindings, check);
    } };
    const id = (v: unknown) => { assert(typeof v === "string" && v.length === 64 && /^[0-9a-f]{64}$/.test(v) && !ids.has(v)); ids.add(v); };
    const allowed: Record<string, string[]> = { NONE: ["DULL_FORMED"], DULL: ["DULL_HELD", "STRUCTURE_FORMED", "STRUCTURE_FORMED_AND_FOLLOWING", "STRUCTURE_PRICE_DISAPPEARED", "SIGNAL_DISAPPEARED", "REFERENCE_INVALIDATED"], STRUCTURE: ["STRUCTURE_HELD", "RETURNED_TO_DULL", "STRUCTURE_FOLLOWING", "STRUCTURE_PRICE_DISAPPEARED", "SIGNAL_DISAPPEARED"] };
    for (const c of raw.conditions) {
        check();
        keys(c, "id outcome referenceRole priceRanges predicates");
        id(c.id);
        assert(c.referenceRole === raw.selectedReference && typeof c.outcome === "string" && (allowed[response.ordinaryState ?? ""] ?? []).includes(c.outcome) && !outcomes.has(c.outcome) && Array.isArray(c.priceRanges) && c.priceRanges.length > 0);
        outcomes.add(c.outcome);
        ranges(c.priceRanges, raw.precisionRanges);
        predicates(c.predicates);
    }
    for (const c of raw.structureFollowConditions) {
        check();
        keys(c, "id outcome relatedStructureId direction originWave nextSameColorStart nextSameColorCount priceRanges precisionRanges predicates");
        id(c.id);
        assert(c.outcome === "SIGNAL_DISAPPEARED" && typeof c.relatedStructureId === "string" && !!c.relatedStructureId && ["TOP", "BOTTOM"].includes(String(c.direction)) && !directions.has(String(c.direction)) && through);
        directions.add(String(c.direction));
        const w = wave(c.originWave, period, through);
        assert(w.sign === (c.direction === "TOP" ? 1 : -1) && Number.isInteger(c.nextSameColorCount) && Number(c.nextSameColorCount) >= 0 && ((c.nextSameColorStart === null) === (c.nextSameColorCount === 0)));
        if (c.nextSameColorStart !== null) {
            timeKey(c.nextSameColorStart, period);
            assert(String(c.nextSameColorStart) > w.end && String(c.nextSameColorStart) <= through);
        }
        precision(c.precisionRanges);
        ranges(c.priceRanges, c.precisionRanges);
        predicates(c.predicates);
    }
    assert(bindings.size <= 1);
    const data = raw as unknown as ForecastDebugData;
    const certain = !!(data.conditions.length || data.structureFollowConditions.some(c => c.priceRanges.length));
    const pending = !!(data.precisionRanges.length || data.structureFollowConditions.some(c => c.precisionRanges.length));
    if (response.targetEndpoint === null)
        assert(!certain && !pending && data.selectedReference === null && !data.farEvaluated && data.structureFollowConditions.length === 0);
    if (response.status === "READY")
        assert(certain);
    if (response.status === "NO_CANDIDATE")
        assert(!certain && !pending);
    if (response.reasonCode === "ROUNDING_BOUNDARY")
        assert(pending);
    if (response.status === "PRECISION_PENDING" && response.reasonCode === "ROUNDING_BOUNDARY")
        assert(!certain && pending);
    check();
    return data;
};
