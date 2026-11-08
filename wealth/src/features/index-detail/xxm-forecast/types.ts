import type { XxmReference, XxmWave } from "../xxm/types";
export const XXM_FORECAST_VERSION = "xxm-key-point-forecast-v0.7-r4.1" as const;
export const XXM_FORECAST_SPEC_HASH = "09b31261ecc10ed7aabb78a51ba89584c6bfbf353c64c465945134dbdabf84c5";
export const FORECAST_PERIODS = ["day", "m30", "m60", "m90", "m120"] as const;
export type ForecastPeriod = typeof FORECAST_PERIODS[number];
export const PERIOD_LABELS: Record<ForecastPeriod, string> = { day: "日线", m30: "30 分钟", m60: "60 分钟", m90: "90 分钟", m120: "120 分钟" };
export type ForecastDirection = "TOP" | "BOTTOM";
export type ForecastExpression = {
    op: "affine";
    pCoefficient: 0;
    cCoefficient: 0 | 1;
    constant: number;
} | {
    op: "scale";
    arg: ForecastExpression;
    factor: number;
} | {
    op: "abs";
    arg: ForecastExpression;
} | {
    op: "sub";
    args: [
        ForecastExpression,
        ForecastExpression
    ];
} | {
    op: "macd";
    e12: number;
    e26: number;
    dea: number;
    field: "dif" | "hist";
} | {
    op: "round3";
    arg: ForecastExpression;
    guard: number;
};
export interface ForecastPriceRange {
    lower: number;
    upper: number | null;
    lowerInclusive: boolean;
    upperInclusive: boolean;
}
export interface ForecastDisplayRange extends ForecastPriceRange {
    displayLower: number | null;
    displayUpper: number | null;
}
export interface ForecastPredicate {
    left: ForecastExpression;
    op: "lt" | "le" | "eq" | "ge" | "gt";
    right: ForecastExpression;
}
export type ForecastOutcome = "DULL_FORMED" | "DULL_HELD" | "STRUCTURE_FORMED" | "STRUCTURE_HELD" | "RETURNED_TO_DULL" | "STRUCTURE_FORMED_AND_FOLLOWING" | "STRUCTURE_FOLLOWING" | "STRUCTURE_PRICE_DISAPPEARED" | "SIGNAL_DISAPPEARED" | "STRUCTURE_DISAPPEARED_AND_DULL_FORMED" | "REFERENCE_INVALIDATED";
export interface ForecastCondition {
    id: string;
    outcome: ForecastOutcome;
    referenceRole: "NEAR" | "FAR";
    priceRanges: ForecastDisplayRange[];
    predicates: ForecastPredicate[];
}
export interface ForecastPrecisionRange {
    priceRange: ForecastPriceRange;
    reason: "ROUNDING_BOUNDARY";
}
export interface ForecastStructureFollowCondition {
    id: string;
    outcome: "SIGNAL_DISAPPEARED";
    relatedStructureId: string;
    direction: ForecastDirection;
    originWave: XxmWave;
    nextSameColorStart: string | null;
    nextSameColorCount: number;
    priceRanges: ForecastDisplayRange[];
    precisionRanges: ForecastPrecisionRange[];
    predicates: ForecastPredicate[];
}
export interface ForecastResponse {
    tsCode: string;
    period: ForecastPeriod;
    forecastVersion: typeof XXM_FORECAST_VERSION;
    forecastSpecHash: string;
    detectorSpecHash: string;
    computedThrough: string | null;
    requestedAsOf: string | null;
    mode: "LATEST" | "REPLAY";
    dataStatus: "READY" | "DELAYED" | "EMPTY";
    ordinaryState: "NONE" | "DULL" | "STRUCTURE" | null;
    direction: ForecastDirection | null;
    targetEndpoint: string | null;
    barsAhead: 1 | null;
    status: "READY" | "NO_CANDIDATE" | "PRECISION_PENDING" | "DELAYED" | "EMPTY";
    reasonCode: string | null;
    forecastId: string;
    display: {
        statusLabel: string;
        targetText: string;
        conditionsText: string;
        asOfText: string;
    };
    applicabilityText: string;
    invalidationText: string;
    refreshAfterMs: number;
}
export interface ForecastDebugData {
    sourceInputId: string | null;
    calendarInputId: string | null;
    precisionPolicy: "rounded3_guarded" | "full_float";
    references: {
        nearest: XxmReference | null;
        farther: XxmReference | null;
    };
    selectedReference: "NEAR" | "FAR" | null;
    nearestDecision: {
        status: "NOT_EVALUATED" | "UNAVAILABLE" | "HAS_RANGE" | "NO_RANGE" | "UNCERTAIN";
        reason: string | null;
    };
    farEvaluated: boolean;
    conditions: ForecastCondition[];
    precisionRanges: ForecastPrecisionRange[];
    structureFollowConditions: ForecastStructureFollowCondition[];
}
export interface ForecastDebugResponse extends ForecastResponse {
    debug: ForecastDebugData;
}
export interface ForecastRowState {
    phase: "idle" | "loading" | "ready" | "error" | "unsupported";
    response: ForecastResponse | ForecastDebugResponse | null;
    error: string;
}
export type ForecastRows = Record<ForecastPeriod, ForecastRowState>;
export interface ForecastRequestResult {
    response: ForecastResponse | ForecastDebugResponse;
    deadline: number;
}
