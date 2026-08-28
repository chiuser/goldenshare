export type SectorDualMomentumScope =
  | "LEVEL_1"
  | "LEVEL_2"
  | "LEVEL_3"
  | "LEVEL_1_CHILDREN"
  | "LEVEL_2_CHILDREN";

export type SectorDualMomentumUrlScope =
  | "level1"
  | "level2"
  | "level3"
  | "level1-children"
  | "level2-children";

export type SectorDualMomentumPeriod = 5 | 10 | 20 | 30;
export type SectorDualMomentumThreshold = 70 | 80 | 90;
export type SectorDualMomentumResultView = "qualified" | "all";
export type SectorDualMomentumStatus = "READY" | "DELAYED" | "EMPTY" | "ERROR";
export type SectorAvailability = "COMPLETE" | "PARTIAL" | "MISSING";
export type DualMomentumSortColumn = "percentile" | "returnPct";
export type DualMomentumSortDirection = "asc" | "desc";

export interface SectorDualMomentumUrlState {
  market: "CN_A";
  debug: boolean;
  tradeDate: string | null;
  scope: SectorDualMomentumUrlScope;
  level1Code: string | null;
  level2Code: string | null;
  period: SectorDualMomentumPeriod;
  threshold: SectorDualMomentumThreshold;
  resultView: SectorDualMomentumResultView;
  sectorCode: string | null;
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
  status: SectorDualMomentumStatus;
  displayText: string;
  asOfTime: string;
}

export interface SectorTradeDateAvailabilityResponse {
  tradeDate: string;
  availability: SectorAvailability;
  expectedSectorCount: number;
  validSectorCount: number;
}

export interface SectorDualMomentumMetaViewModel {
  status: "READY" | "DELAYED";
  tradingDay: SectorTradingDayResponse;
  pageStatus: SectorPageStatusResponse;
  message: string | null;
  formula: {
    formulaKey: "sector-dual-momentum";
    formulaVersion: 1;
    basisFormulaKey: "sector-cross-sectional-momentum";
    basisFormulaVersion: 1;
    periods: SectorDualMomentumPeriod[];
    leadingThresholds: SectorDualMomentumThreshold[];
    minimumGroupSize: 3;
    scopes: SectorDualMomentumScope[];
  };
  defaults: {
    scope: "LEVEL_1";
    period: 20;
    leadingThreshold: 80;
    resultView: "QUALIFIED";
  };
  hierarchy: {
    hierarchyVersion: string;
    publishedAt: string;
    nodes: SectorHierarchyNodeResponse[];
  };
  coverageStartDate: string;
  coverageEndDate: string;
  tradeDates: SectorTradeDateAvailabilityResponse[];
  level1Nodes: SectorHierarchyNodeResponse[];
  level2Nodes: SectorHierarchyNodeResponse[];
  level3Nodes: SectorHierarchyNodeResponse[];
}

export type DualMomentumAbsoluteStatus = "POSITIVE" | "NOT_POSITIVE" | "UNAVAILABLE";
export type DualMomentumRelativeStatus = "LEADING" | "NOT_LEADING" | "SAMPLE_INSUFFICIENT" | "UNAVAILABLE";
export type DualMomentumQualificationStatus = "QUALIFIED" | "NOT_QUALIFIED" | "NOT_EVALUATED";
export type DualMomentumCoordinateStatus = "PLOTTABLE" | "UNAVAILABLE";
export type DualMomentumDisplayStatus =
  | "QUALIFIED"
  | "UP_NOT_LEADING"
  | "NOT_UP_LEADING"
  | "NOT_UP_NOT_LEADING"
  | "SAMPLE_INSUFFICIENT"
  | "DATA_INSUFFICIENT";
export type DualMomentumMissingReason =
  | "HISTORY_INSUFFICIENT"
  | "DATE_MISSING"
  | "CLOSE_MISSING"
  | "CLOSE_NON_POSITIVE"
  | "PCT_CHANGE_MISSING";

export interface SectorDualMomentumRowViewModel {
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
  absoluteStatus: DualMomentumAbsoluteStatus;
  relativeStatus: DualMomentumRelativeStatus;
  qualificationStatus: DualMomentumQualificationStatus;
  coordinateStatus: DualMomentumCoordinateStatus;
  displayStatus: DualMomentumDisplayStatus;
  missingReason: DualMomentumMissingReason | null;
  returnText: string;
  rankText: string;
  percentileText: string;
  directionClass: "up" | "down" | "flat" | "muted";
  statusText: string;
  statusClass: string;
}

export interface SectorDualMomentumResultsViewModel {
  status: "READY" | "DELAYED";
  tradingDay: SectorTradingDayResponse;
  pageStatus: SectorPageStatusResponse;
  message: string | null;
  analysis: {
    formulaKey: "sector-dual-momentum";
    formulaVersion: 1;
    basisFormulaKey: "sector-cross-sectional-momentum";
    basisFormulaVersion: 1;
    hierarchyVersion: string;
    scope: SectorDualMomentumScope;
    period: SectorDualMomentumPeriod;
    leadingThreshold: SectorDualMomentumThreshold;
    minimumGroupSize: 3;
    parentSelection: {
      level1Code: string | null;
      level1Name: string | null;
      level2Code: string | null;
      level2Name: string | null;
    };
    totalCount: number;
    calculableCount: number;
    qualifiedCount: number;
    insufficientCount: number;
    plottableCount: number;
    items: SectorDualMomentumRowViewModel[];
  };
}

export type SectorDualMomentumResultsAdapterResult =
  | { kind: "ready"; data: SectorDualMomentumResultsViewModel }
  | { kind: "empty"; message: string }
  | { kind: "error"; message: string; retryable: boolean };

export type DualMomentumViewState =
  | { kind: "loading"; meta?: SectorDualMomentumMetaViewModel }
  | {
      kind: "ready" | "delayed";
      meta: SectorDualMomentumMetaViewModel;
      results: SectorDualMomentumResultsViewModel;
      selectedCode: string | null;
    }
  | { kind: "empty"; meta: SectorDualMomentumMetaViewModel; message: string }
  | { kind: "error"; meta?: SectorDualMomentumMetaViewModel; message: string; retryable: boolean };

export interface SectorDualMomentumResultsRequest {
  market: "CN_A";
  tradeDate?: string;
  scope: SectorDualMomentumScope;
  level1Code?: string;
  level2Code?: string;
  period: SectorDualMomentumPeriod;
  leadingThreshold: SectorDualMomentumThreshold;
  hierarchyVersion: string;
  debug?: 0 | 1;
}
