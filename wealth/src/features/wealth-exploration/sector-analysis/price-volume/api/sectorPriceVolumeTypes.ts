export type PriceVolumeScope =
  | "LEVEL_1"
  | "LEVEL_2"
  | "LEVEL_3"
  | "LEVEL_1_CHILDREN"
  | "LEVEL_2_CHILDREN";

export type PriceVolumeUrlScope =
  | "level1"
  | "level2"
  | "level3"
  | "level1-children"
  | "level2-children";

export type PriceVolumePeriod = 1 | 5 | 10 | 20 | 30;
export type PriceVolumeHistoryRange = 20 | 30 | 60;
export type PriceVolumeState = "JOINT" | "PRICE_ONLY" | "AMOUNT_ONLY" | "NEUTRAL";
export type PriceVolumeStateFilter = "all" | "joint" | "price" | "amount" | "neutral";
export type PriceVolumeSortBy = "price-momentum" | "amount-activity";
export type PriceVolumeSortDirection = "desc" | "asc";
export type PriceVolumeAvailability = "COMPLETE" | "PARTIAL" | "MISSING";
export type PriceVolumeMissingReason =
  | "HISTORY_INSUFFICIENT"
  | "DATE_MISSING"
  | "PCT_CHANGE_MISSING"
  | "CLOSE_MISSING"
  | "CLOSE_NON_POSITIVE"
  | "AMOUNT_MISSING"
  | "AMOUNT_NON_FINITE"
  | "AMOUNT_NEGATIVE"
  | "PRIOR_AMOUNT_AVERAGE_NON_POSITIVE";

export interface PriceVolumeUrlState {
  tradeDate: string | null;
  scope: PriceVolumeUrlScope;
  level1Code: string | null;
  level2Code: string | null;
  period: PriceVolumePeriod;
  stateFilter: PriceVolumeStateFilter;
  sortBy: PriceVolumeSortBy;
  sortDirection: PriceVolumeSortDirection;
  sectorCode: string | null;
  historyRange: PriceVolumeHistoryRange;
}

export interface PriceVolumeHierarchyNode {
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

export interface PriceVolumeTradeDateAvailability {
  tradeDate: string;
  availability: PriceVolumeAvailability;
  expectedSectorCount: number;
  validSectorCount: number;
}

export interface PriceVolumeMetaViewModel {
  formulaKey: "sector-price-volume-distribution";
  formulaVersion: 1;
  market: "CN_A";
  periods: PriceVolumePeriod[];
  historyRanges: PriceVolumeHistoryRange[];
  scopes: PriceVolumeScope[];
  states: PriceVolumeState[];
  defaults: {
    scope: "LEVEL_1";
    period: 20;
    stateFilter: "ALL";
    sortBy: "PRICE_MOMENTUM";
    sortDirection: "DESC";
    historyRange: 20;
  };
  dateCoverageBasis: "INDUSTRY_DAILY";
  dateContext: {
    expectedTradeDate: string;
    defaultTradeDate: string | null;
    defaultStatus: "READY" | "DELAYED" | "EMPTY";
    displayText: string;
  };
  hierarchy: {
    hierarchyVersion: string;
    publishedAt: string;
    nodes: PriceVolumeHierarchyNode[];
  };
  coverageStartDate: string;
  coverageEndDate: string;
  tradeDates: PriceVolumeTradeDateAvailability[];
  level1Nodes: PriceVolumeHierarchyNode[];
  level2Nodes: PriceVolumeHierarchyNode[];
  level3Nodes: PriceVolumeHierarchyNode[];
}

export interface PriceVolumeSnapshotRowViewModel {
  sectorCode: string;
  sectorName: string;
  industryLevel: 1 | 2 | 3;
  hierarchyPath: string;
  parentSectorCode: string | null;
  parentSectorName: string | null;
  rootSectorCode: string;
  rootSectorName: string;
  priceMomentumPct: number | null;
  amountActivityPct: number | null;
  priceRank: number | null;
  priceRankableCount: number;
  amountRank: number | null;
  amountRankableCount: number;
  state: PriceVolumeState | null;
  priceMissingReason: PriceVolumeMissingReason | null;
  amountMissingReason: PriceVolumeMissingReason | null;
  priceText: string;
  amountText: string;
  stateText: string;
  stateClass: string;
  canDrillDown: boolean;
}

export interface PriceVolumeSnapshotViewModel {
  formulaKey: "sector-price-volume-distribution";
  formulaVersion: 1;
  hierarchyVersion: string;
  observedTradeDate: string;
  availability: PriceVolumeAvailability;
  scope: PriceVolumeScope;
  level1Code: string | null;
  level2Code: string | null;
  period: PriceVolumePeriod;
  totalCount: number;
  coordinateCount: number;
  missingCoordinateCount: number;
  rows: PriceVolumeSnapshotRowViewModel[];
}

export interface PriceVolumeHistoryPointViewModel {
  tradeDate: string;
  priceMomentumPct: number | null;
  amountActivityPct: number | null;
  priceMissingReason: PriceVolumeMissingReason | null;
  amountMissingReason: PriceVolumeMissingReason | null;
}

export interface PriceVolumeDetailsViewModel {
  formulaKey: "sector-price-volume-distribution";
  formulaVersion: 1;
  hierarchyVersion: string;
  observedTradeDate: string;
  availability: PriceVolumeAvailability;
  scope: PriceVolumeScope;
  level1Code: string | null;
  level2Code: string | null;
  period: PriceVolumePeriod;
  historyRange: PriceVolumeHistoryRange;
  selected: {
    sectorCode: string;
    sectorName: string;
    industryLevel: 1 | 2 | 3;
    hierarchyPath: string;
    parentSectorCode: string | null;
    rootSectorCode: string;
  };
  history: PriceVolumeHistoryPointViewModel[];
}

export interface PriceVolumeSnapshotRequest {
  market: "CN_A";
  tradeDate: string;
  scope: PriceVolumeScope;
  level1Code?: string;
  level2Code?: string;
  period: PriceVolumePeriod;
  hierarchyVersion: string;
}

export interface PriceVolumeDetailsRequest extends PriceVolumeSnapshotRequest {
  historyRange: PriceVolumeHistoryRange;
  sectorCode: string;
}

export type PriceVolumeSnapshotAdapterResult =
  | { kind: "ready"; data: PriceVolumeSnapshotViewModel }
  | { kind: "empty"; data: PriceVolumeSnapshotViewModel; message: string }
  | { kind: "error"; message: string; retryable: boolean };

export type PriceVolumeDetailsAdapterResult =
  | { kind: "ready"; data: PriceVolumeDetailsViewModel }
  | { kind: "empty"; data: PriceVolumeDetailsViewModel; message: string }
  | { kind: "error"; message: string; retryable: boolean };

export type PriceVolumeDetailsState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; data: PriceVolumeDetailsViewModel }
  | { kind: "empty"; data: PriceVolumeDetailsViewModel; message: string }
  | { kind: "error"; message: string; retryable: boolean };

export type PriceVolumeViewState =
  | { kind: "loading"; meta?: PriceVolumeMetaViewModel }
  | { kind: "ready" | "delayed"; meta: PriceVolumeMetaViewModel; snapshot: PriceVolumeSnapshotViewModel; pending: boolean }
  | { kind: "empty"; meta?: PriceVolumeMetaViewModel; snapshot?: PriceVolumeSnapshotViewModel; message: string }
  | { kind: "error"; meta?: PriceVolumeMetaViewModel; message: string; retryable: boolean };
