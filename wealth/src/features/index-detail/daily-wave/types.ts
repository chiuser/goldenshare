import type { IndexCandlePoint } from "../model/indexDetailTypes";

// HTTP facts mirror DailyWaveReadyDto/EmptyDto (LLD 14.6.1, 15.3, 15.7).
// Decimal values remain source text; rendering never replaces these facts.
export type DailyWaveValidity = "VALID" | "INVALID" | "UNKNOWN";
export type DailyWaveDirection = "UP" | "DOWN";
export type DailyWaveMetric = "CLOSE" | "DIF";
export interface DailyWavePoint { date: string; close: string; dif: string; dea: string; macd: string; }
export interface DailyWaveTurnBase {
  id: string; metric: DailyWaveMetric; value: string; firstDate: string; lastDate: string; plateauDates: string[];
}
export interface DailyWaveConfirmedTurn extends DailyWaveTurnBase { kind: "MAX" | "MIN"; confirmedAt: string; }
export interface DailyWavePendingTurn extends DailyWaveTurnBase { kind: null; confirmedAt: null; possibleKind: "MAX" | "MIN" | null; }
export interface DailyWaveExtreme { value: string; dates: string[]; }
export interface DailyWaveHistogramExtreme extends DailyWaveExtreme { absoluteLength: string; }
export interface DailyWaveExtrema {
  maxClose: DailyWaveExtreme; minClose: DailyWaveExtreme; maxDif: DailyWaveExtreme; minDif: DailyWaveExtreme;
  longestRed: DailyWaveHistogramExtreme | null; longestGreen: DailyWaveHistogramExtreme | null;
}
export interface DailyWaveColorSegment {
  id: string; color: "RED" | "GREEN"; startDate: string; endDate: string; lastColoredDate: string;
  coloredCount: number; zeroDates: string[]; isLeftComplete: boolean; isEnded: boolean;
  endKnownAt: string | null; turnIds: string[]; extrema: DailyWaveExtrema;
}
export interface DailyWaveDateRange { startDate: string; endDate: string; }
export interface DailyWavePriceEndpoint { date: string; closedAt: string; close: string; tiedDates: string[]; }
export interface DailyWaveIssue { message: string; dates: string[]; }
export interface DailyWavePricePoint { date: string; close: string; }
export interface DailyWavePriceComparison { fromDate: string; toDate: string; relation: "HIGHER" | "LOWER" | "EQUAL"; }
export interface DailyWaveInternalPriceRelations {
  highs: DailyWavePricePoint[]; lows: DailyWavePricePoint[];
  highComparisons: DailyWavePriceComparison[]; lowComparisons: DailyWavePriceComparison[];
  status: "INSUFFICIENT" | "RISING" | "FALLING" | "MIXED" | "EQUAL";
}
export interface DailyWaveTailReview {
  range: DailyWaveDateRange | null; turnIds: string[]; extrema: DailyWaveExtrema | null;
  strictlyBrokeStart: boolean | null; touchedStart: boolean | null;
}
export interface DailyWavePriceSegment {
  id: string; sourceColorSegmentId: string; previousColorSegmentId: string | null; direction: DailyWaveDirection;
  generated: boolean; startSearchRange: DailyWaveDateRange | null; endSearchRange: DailyWaveDateRange | null;
  start: DailyWavePriceEndpoint | null; end: DailyWavePriceEndpoint | null; startKnownAt: string | null;
  isEnded: boolean; endKnownAt: string | null; startValidity: DailyWaveValidity; endValidity: DailyWaveValidity;
  endpointValidity: DailyWaveValidity; issues: DailyWaveIssue[]; internalPriceRelations: DailyWaveInternalPriceRelations | null;
  tailReview: DailyWaveTailReview; extrema: DailyWaveExtrema | null; difTurnIds: string[];
}
export interface DailyWaveEndpointOffset { difTurnId: string; priceEndpoint: "START" | "END"; tradingDayOffset: number; }
export interface DailyWaveMapping {
  sourceColorSegmentId: string; priceSegmentId: string; colorRange: DailyWaveDateRange;
  priceRange: DailyWaveDateRange | null; observationIntersection: DailyWaveDateRange | null;
  priceObservationIntersection: DailyWaveDateRange | null; sourceTurnIds: string[]; priceTurnIds: string[];
  endpointOffsets: DailyWaveEndpointOffset[]; issues: DailyWaveIssue[];
}
export interface DailyWaveBarStats { coloredCount: number; longestBar: DailyWaveHistogramExtreme; }
export interface DailyWaveThreeBarStats { previous: DailyWaveBarStats; opposite: DailyWaveBarStats; next: DailyWaveBarStats; }
export interface DailyWaveThreePriceExtrema { previous: DailyWaveExtreme; opposite: DailyWaveExtreme; next: DailyWaveExtreme; }
export interface DailyWaveShortOppositeSegment {
  previousColorSegmentId: string; oppositeColorSegmentId: string; nextColorSegmentId: string;
  barStats: DailyWaveThreeBarStats; priceHighs: DailyWaveThreePriceExtrema; priceLows: DailyWaveThreePriceExtrema; difTurnIds: string[];
}
export interface DailyWaveCoverageCounts { leftIncomplete: number; ungenerated: number; invalid: number; unknown: number; }
export interface DailyWaveCoverage {
  mainPointCount: number; leftIncompleteColorSegmentIds: string[]; ungeneratedPriceSegmentIds: string[];
  invalidPriceSegmentIds: string[]; unknownPriceSegmentIds: string[]; counts: DailyWaveCoverageCounts;
}
export interface DailyWaveHeader {
  schemaVersion: 1; tsCode: "000001.SH"; period: "day"; ruleId: "xxm-daily-wave-review-v0.1";
  calculationId: string; calculatedAt: string; requestedStart: "2023-10-24"; requestedEnd: "2026-10-21";
}
export interface DailyWaveEmptyResponse extends DailyWaveHeader { status: "empty"; }
export interface DailyWaveReadyResponse extends DailyWaveHeader {
  status: "ready"; observationStart: string; observationEnd: string; contextStart: string; contextEnd: string; asOf: string;
  sourcePoints: DailyWavePoint[]; turns: DailyWaveConfirmedTurn[]; pendingTurns: DailyWavePendingTurn[];
  colorSegments: DailyWaveColorSegment[]; segments: DailyWavePriceSegment[]; mappings: DailyWaveMapping[];
  shortOppositeSegments: DailyWaveShortOppositeSegment[]; coverage: DailyWaveCoverage;
}
export type DailyWaveResponse = DailyWaveReadyResponse | DailyWaveEmptyResponse;
export type DailyWavePhase = "closed" | "loading" | "empty" | "ready" | "error" | "timeout" | "mismatch";
export interface DailyWaveReviewState {
  supported: boolean; enabled: boolean; phase: DailyWavePhase; response: DailyWaveResponse | null;
  candles: IndexCandlePoint[]; dataKey: string | null; errorMessage: string;
  toggle: () => void; retry: () => void; close: () => void;
}
