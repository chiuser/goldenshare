export type SectorRelativeRotationScope =
  | "LEVEL_1"
  | "LEVEL_2"
  | "LEVEL_3"
  | "LEVEL_1_CHILDREN"
  | "LEVEL_2_CHILDREN";

export type SectorRelativeRotationUrlScope =
  | "level1"
  | "level2"
  | "level3"
  | "level1-children"
  | "level2-children";

export type SectorRelativeRotationPeriod = 5 | 10 | 20 | 30;
export type SectorRelativeRotationTrailLength = 20 | 30 | 60;
export type SectorRelativeRotationQuadrantFilter =
  | "all"
  | "leading-improving"
  | "weak-improving"
  | "strong-not-improving"
  | "weak-not-improving";
export type SectorRelativeRotationStatus = "READY" | "DELAYED" | "EMPTY" | "ERROR";
export type SectorAvailability = "COMPLETE" | "PARTIAL" | "MISSING";
export type RelativeRotationStatus =
  | "LEADING_IMPROVING"
  | "WEAK_IMPROVING"
  | "STRONG_NOT_IMPROVING"
  | "WEAK_NOT_IMPROVING"
  | "SAMPLE_INSUFFICIENT"
  | "DATA_INSUFFICIENT";
export type RelativeCoordinateStatus = "PLOTTABLE" | "UNAVAILABLE";
export type RelativeMissingReason =
  | "HISTORY_INSUFFICIENT"
  | "DATE_MISSING"
  | "CLOSE_MISSING"
  | "CLOSE_NON_POSITIVE"
  | "PCT_CHANGE_MISSING";

export interface SectorRelativeRotationUrlState {
  market: "CN_A";
  debug: boolean;
  tradeDate: string | null;
  scope: SectorRelativeRotationUrlScope;
  level1Code: string | null;
  level2Code: string | null;
  period: SectorRelativeRotationPeriod;
  trailLength: SectorRelativeRotationTrailLength;
  sectorCode: string | null;
  quadrant: SectorRelativeRotationQuadrantFilter;
  search: string;
}

export interface SectorHierarchyNodeResponse {
  sectorCode: string;
  sectorName: string;
  industryLevel: 1 | 2 | 3;
  parentSectorCode: string | null;
  parentSectorName: string | null;
  rootSectorCode: string;
  rootSectorName: string;
  hierarchyPath: string;
  displayOrder: number;
  isLeaf: boolean;
}

export interface SectorTradingDayResponse {
  expectedTradeDate: string;
  observedTradeDate: string | null;
  expectedAvailability: SectorAvailability;
  expectedSectorCount: number;
  expectedValidSectorCount: number;
  observedAvailability: SectorAvailability | null;
  observedValidSectorCount: number;
}

export interface SectorPageStatusResponse {
  status: SectorRelativeRotationStatus;
  displayText: string;
  asOfTime: string;
}

export interface SectorTradeDateAvailabilityResponse {
  tradeDate: string;
  availability: SectorAvailability;
  expectedSectorCount: number;
  validSectorCount: number;
}

export interface SectorRelativeRotationMetaViewModel {
  status: "READY" | "DELAYED";
  tradingDay: SectorTradingDayResponse;
  pageStatus: SectorPageStatusResponse;
  message: string | null;
  formula: {
    formulaKey: "sector-relative-rotation";
    formulaVersion: 1;
    basisFormulaKey: "sector-cross-sectional-momentum";
    basisFormulaVersion: 1;
    periods: SectorRelativeRotationPeriod[];
    improvementLookbackDays: 5;
    trailLengths: SectorRelativeRotationTrailLength[];
    minimumGroupSize: 3;
    scopes: SectorRelativeRotationScope[];
    xDomain: [0, 100];
    xSplit: 50;
    ySplit: 0;
  };
  defaults: { scope: "LEVEL_1"; period: 20; trailLength: 20; quadrantFilter: "ALL" };
  hierarchy: { hierarchyVersion: string; publishedAt: string; nodes: SectorHierarchyNodeResponse[] };
  coverageStartDate: string;
  coverageEndDate: string;
  tradeDates: SectorTradeDateAvailabilityResponse[];
  level1Nodes: SectorHierarchyNodeResponse[];
  level2Nodes: SectorHierarchyNodeResponse[];
  level3Nodes: SectorHierarchyNodeResponse[];
}

export interface SectorRelativeRotationRowViewModel {
  sectorCode: string;
  sectorName: string;
  industryLevel: 1 | 2 | 3;
  parentSectorCode: string | null;
  parentSectorName: string | null;
  hierarchyPath: string;
  canDrillDown: boolean;
  returnPct: number | null;
  strengthRank: number | null;
  percentile: number | null;
  percentileDelta5d: number | null;
  rotationStatus: RelativeRotationStatus;
  coordinateStatus: RelativeCoordinateStatus;
  currentMissingReason: RelativeMissingReason | null;
  comparisonMissingReason: RelativeMissingReason | null;
  returnText: string;
  percentileText: string;
  deltaText: string;
  statusText: string;
  statusClass: string;
  directionClass: "up" | "down" | "flat" | "muted";
}

export interface SectorRelativeRotationTrailPointViewModel {
  tradeDate: string;
  returnPct: number | null;
  percentile: number | null;
  percentileDelta5d: number | null;
  rotationStatus: RelativeRotationStatus;
  coordinateStatus: RelativeCoordinateStatus;
  currentMissingReason: RelativeMissingReason | null;
  comparisonMissingReason: RelativeMissingReason | null;
}

export interface SectorRelativeRotationResultsViewModel {
  status: "READY" | "DELAYED";
  tradingDay: SectorTradingDayResponse;
  pageStatus: SectorPageStatusResponse;
  message: string | null;
  analysis: {
    formulaKey: "sector-relative-rotation";
    formulaVersion: 1;
    basisFormulaKey: "sector-cross-sectional-momentum";
    basisFormulaVersion: 1;
    hierarchyVersion: string;
    scope: SectorRelativeRotationScope;
    period: SectorRelativeRotationPeriod;
    improvementLookbackDays: 5;
    trailLength: SectorRelativeRotationTrailLength;
    minimumGroupSize: 3;
    parentSelection: { level1Code: string | null; level1Name: string | null; level2Code: string | null; level2Name: string | null };
    selectedSectorCode: string;
    groupInterpretation: "QUADRANT" | "SAMPLE_INSUFFICIENT";
    totalCount: number;
    currentCalculableCount: number;
    plottableCount: number;
    missingCoordinateCount: number;
    quadrantCounts: { leadingImproving: number; weakImproving: number; strongNotImproving: number; weakNotImproving: number };
    items: SectorRelativeRotationRowViewModel[];
    selectedTrail: { sectorCode: string; requestedLength: SectorRelativeRotationTrailLength; dateSlotCount: number; points: SectorRelativeRotationTrailPointViewModel[] };
    scopeTitle: string;
  };
}

export interface SectorRelativeRotationResultsRequest {
  market: "CN_A";
  tradeDate?: string;
  scope: SectorRelativeRotationScope;
  level1Code?: string;
  level2Code?: string;
  period: SectorRelativeRotationPeriod;
  trailLength: SectorRelativeRotationTrailLength;
  sectorCode?: string;
  hierarchyVersion: string;
  debug?: 0 | 1;
}

export type SectorRelativeRotationAdapterResult =
  | { kind: "ready"; data: SectorRelativeRotationResultsViewModel }
  | { kind: "empty"; message: string }
  | { kind: "error"; message: string; retryable: boolean };

export type RelativeRotationViewState =
  | { kind: "loading"; meta?: SectorRelativeRotationMetaViewModel }
  | { kind: "ready" | "delayed"; meta: SectorRelativeRotationMetaViewModel; results: SectorRelativeRotationResultsViewModel; pending: boolean }
  | { kind: "empty"; meta: SectorRelativeRotationMetaViewModel; message: string }
  | { kind: "error"; meta?: SectorRelativeRotationMetaViewModel; message: string; retryable: boolean };
