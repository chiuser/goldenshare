import type { XxmRearmRecord } from "../xxm/types";
export const XXM_FORECAST_VERSION = "xxm-key-point-forecast-v0.3-r2" as const;
export const XXM_FORECAST_SPEC_HASH = "add5e3636e6972e267bdda81c05e0e864f600f9e67d658b6a560445e39dda6d8";
export const FORECAST_PERIODS = ["day", "m60", "m90", "m120"] as const;
export type ForecastPeriod = typeof FORECAST_PERIODS[number];
export const PERIOD_LABELS: Record<ForecastPeriod, string> = { day: "日线", m60: "60 分钟", m90: "90 分钟", m120: "120 分钟" };
export type ForecastDirection = "TOP" | "BOTTOM";
export interface ForecastPriceRange {
  lower: number | null; upper: number | null; lowerInclusive: boolean; upperInclusive: boolean;
}
export interface ForecastReference { startTime: string; endTime: string; price: number; dif: number }
export type ForecastRoute = "dif_turn" | "color_flip";
export interface ForecastCloseRange extends ForecastPriceRange {
  route: ForecastRoute; displayLower: number; displayUpper: number | null; displayPlaces: 2 | 4;
}
export type ForecastExpression =
  | { op: "affine"; pCoefficient: number; cCoefficient: number; constant: number }
  | { op: "scale"; arg: ForecastExpression; factor: number }
  | { op: "abs"; arg: ForecastExpression }
  | { op: "sub"; args: [ForecastExpression, ForecastExpression] }
  | { op: "round3"; arg: ForecastExpression; guard: number };
export interface ForecastCondition { left: ForecastExpression; op: "lt" | "le" | "eq" | "ge" | "gt"; right: ForecastExpression }
export interface ForecastReferenceTransition { endpoint: string; fromReference: ForecastReference; toReference: ForecastReference }
export interface ForecastNextBarOutcomes {
  endpoint: string; initialReference: ForecastReference;
  branches: Array<{ branchId: string; priceRange: ForecastPriceRange;
    outcome: "PRESERVED" | "REFERENCE_SWITCHED" | "STRUCTURE_CONFIRMED" | "CANCELLED" | "ZERO_RESET" | "PRECISION_UNRESOLVED";
    reference: ForecastReference | null; route: ForecastRoute | "dif_break" | "dif_break_on_flip" | null }>;
}
export interface ForecastResponse {
  tsCode: "000001.SH"; period: ForecastPeriod;
  forecastVersion: typeof XXM_FORECAST_VERSION; forecastSpecHash: string; detectorSpecHash: string;
  sourceInputId: string | null; calendarInputId: string | null; computedThrough: string | null; requestedAsOf: string | null;
  mode: "LATEST" | "REPLAY"; dataStatus: "READY" | "DELAYED" | "EMPTY";
  rearmContext: XxmRearmRecord | null;
  nextBarOutcomes: ForecastNextBarOutcomes | null;
  ordinaryState: "NONE" | "DULL" | "STRUCTURE" | null; direction: ForecastDirection | null;
  status: "READY" | "CONDITIONAL_ENTRY" | "ENTRY_ONLY" | "NO_CANDIDATE" | "CONFIRMED" | "PRECISION_PENDING" | "DELAYED" | "EMPTY";
  reasonCode: string | null; precisionPolicy: "rounded3_guarded" | "full_float"; forecastId: string;
  targetEndpoint: string | null; barsAhead: number | null;
  activation: { endpoint: string; ranges: Array<{ entryRangeId: string; priceRange: ForecastPriceRange; reference: ForecastReference }>;
    exclusions: Array<{ priceRange: ForecastPriceRange; reason: string }> } | null;
  assumption: { policy: "entry_range_then_flat"; activationEndpoint: string | null; intermediateEndpoints: string[]; intermediateCloseExpression: ForecastExpression } | null;
  targetEntryRanges: Array<{ entryRangeIds: string[]; priceRange: ForecastPriceRange }>;
  targetEntryExclusions: Array<{ entryRangeIds: string[]; priceRange: ForecastPriceRange; reason: string }>;
  relations: Array<{ relationId: string; entryRangeIds: string[]; entryDomain: ForecastPriceRange | null; reference: ForecastReference; initialReference: ForecastReference; referenceTransitions: ForecastReferenceTransition[];
    route: ForecastRoute; prefixConditions: ForecastCondition[]; targetConditions: ForecastCondition[] }>;
  commonConditions: Array<{ relationId: string; entryRangeIds: string[]; entryDomain: ForecastPriceRange | null; reference: ForecastReference;
    route: ForecastRoute; closeRanges: ForecastCloseRange[] }>;
  examples: Array<{ preClose: number; entryRangeId: string; closeRanges: Array<ForecastCloseRange & { relationId: string }> }>;
  applicabilityText: string; invalidationText: string;
  confirmedAt: string | null; confirmedDirection: ForecastDirection | null;
  display: { statusLabel: string; targetText: string; conditionsText: string; asOfText: string };
  refreshAfterMs: number;
}
export interface ForecastRowState {
  phase: "idle" | "loading" | "ready" | "error" | "unsupported";
  response: ForecastResponse | null; error: string;
}
export type ForecastRows = Record<ForecastPeriod, ForecastRowState>;
