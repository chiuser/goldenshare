export type SectorMomentumScope =
  | "LEVEL_1"
  | "LEVEL_2"
  | "LEVEL_3"
  | "LEVEL_1_CHILDREN"
  | "LEVEL_2_CHILDREN";

export type SectorMomentumUrlScope =
  | "level1"
  | "level2"
  | "level3"
  | "level1-children"
  | "level2-children";

export type SectorMomentumDirection = "GAINERS" | "LOSERS";
export type SectorMomentumUrlDirection = "gainers" | "losers";
export type SectorMomentumPeriod = 1 | 5 | 10 | 20 | 30;
export type SectorHistoryRange = 20 | 30 | 60;
export type SectorAnalysisStatus = "READY" | "DELAYED" | "EMPTY" | "ERROR";
export type SectorAvailability = "COMPLETE" | "PARTIAL" | "MISSING";

export interface SectorMomentumUrlState {
  market: "CN_A";
  debug: boolean;
  tradeDate: string | null;
  scope: SectorMomentumUrlScope;
  level1Code: string | null;
  level2Code: string | null;
  period: SectorMomentumPeriod;
  direction: SectorMomentumUrlDirection;
  range: SectorHistoryRange;
  sectorCode: string | null;
}

export interface SectorFormulaResponse {
  formulaKey: "sector-cross-sectional-momentum";
  formulaVersion: 1;
  periods: SectorMomentumPeriod[];
  historyRanges: SectorHistoryRange[];
  scopes: SectorMomentumScope[];
  directions: SectorMomentumDirection[];
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

export interface SectorTradeDateAvailabilityResponse {
  tradeDate: string;
  availability: SectorAvailability;
  expectedSectorCount: number;
  validSectorCount: number;
}

export interface SectorAnalysisMetaResponse {
  formula: SectorFormulaResponse;
  hierarchy: {
    hierarchyVersion: string;
    publishedAt: string;
    nodes: SectorHierarchyNodeResponse[];
  };
  coverageStartDate: string;
  coverageEndDate: string;
  tradeDates: SectorTradeDateAvailabilityResponse[];
}

export interface SectorAnalysisTradingDayResponse {
  expectedTradeDate: string;
  observedTradeDate: string | null;
  expectedAvailability: SectorAvailability;
  expectedSectorCount: number;
  expectedValidSectorCount: number;
  observedAvailability: SectorAvailability | null;
  observedValidSectorCount: number;
}

export interface SectorAnalysisPageStatusResponse {
  status: SectorAnalysisStatus;
  displayText: string;
  asOfTime: string;
}

export interface SectorRankingRowResponse {
  listPosition: number;
  strengthRank: number | null;
  sectorCode: string;
  sectorName: string;
  industryLevel: 1 | 2 | 3;
  parentSectorCode: string | null;
  parentSectorName: string | null;
  hierarchyPath: string;
  returnPct: number | null;
  percentile: number | null;
  canDrillDown: boolean;
}

export interface SectorRankingResponse {
  formulaKey: "sector-cross-sectional-momentum";
  formulaVersion: 1;
  hierarchyVersion: string;
  scope: SectorMomentumScope;
  period: SectorMomentumPeriod;
  direction: SectorMomentumDirection;
  parentSelection: {
    level1Code: string | null;
    level1Name: string | null;
    level2Code: string | null;
    level2Name: string | null;
  };
  totalCount: number;
  calculableCount: number;
  rows: SectorRankingRowResponse[];
}

export interface SectorMomentumRankingsResponse {
  status: SectorAnalysisStatus;
  tradingDay: SectorAnalysisTradingDayResponse;
  pageStatus: SectorAnalysisPageStatusResponse;
  ranking: SectorRankingResponse | null;
  message: string | null;
  exceptionCode: string | null;
}

export interface SectorMomentumDetailResponse {
  sectorCode: string;
  sectorName: string;
  industryLevel: 1 | 2 | 3;
  hierarchyPath: string;
  scopeTitle: string;
  returnPct: number | null;
  percentile: number | null;
  currentScopeStrengthRank: number | null;
  currentScopeCalculableCount: number;
  currentScopeTotalCount: number;
  globalLevelStrengthRank: number | null;
  globalLevelCalculableCount: number;
  globalLevelTotalCount: number;
  parentStrengthRank: number | null;
  parentCalculableCount: number | null;
  parentTotalCount: number | null;
  formulaKey: "sector-cross-sectional-momentum";
  formulaVersion: 1;
  hierarchyVersion: string;
}

export interface SectorMomentumHistoryResponse {
  status: SectorAnalysisStatus;
  tradingDay: SectorAnalysisTradingDayResponse;
  pageStatus: SectorAnalysisPageStatusResponse;
  detail: SectorMomentumDetailResponse | null;
  rollingReturns: Array<{ tradeDate: string; returnPct: number | null }>;
  historicalRanks: Array<{
    tradeDate: string;
    strengthRank: number | null;
    calculableCount: number;
    totalCount: number;
    percentile: number | null;
  }>;
  message: string | null;
  exceptionCode: string | null;
}

export type SectorMemberStatus = "READY" | "EMPTY" | "ERROR";

export interface SectorMemberRowResponse {
  stockName: string | null;
  stockCode: string;
  close: number | null;
  returnPct: number | null;
}

export interface SectorMemberDetailResponse {
  status: SectorMemberStatus;
  message: string | null;
  exceptionCode: string | null;
  tradeDate: string;
  hierarchyVersion: string;
  sectorCode: string;
  sectorName: string;
  period: SectorMomentumPeriod;
  direction: SectorMomentumDirection;
  totalMemberCount: number;
  closeAvailableCount: number;
  calculableCount: number;
  rows: SectorMemberRowResponse[];
}

export interface SectorMomentumMetaViewModel extends SectorAnalysisMetaResponse {
  level1Nodes: SectorHierarchyNodeResponse[];
  level2Nodes: SectorHierarchyNodeResponse[];
  level3Nodes: SectorHierarchyNodeResponse[];
}

export interface SectorRankingRowViewModel extends SectorRankingRowResponse {
  returnText: string;
  returnBarWidthPct: number;
  percentileText: string;
  strengthRankText: string;
  directionClass: "up" | "down" | "flat" | "muted";
}

export interface SectorMomentumRankingViewModel extends Omit<SectorRankingResponse, "rows"> {
  rows: SectorRankingRowViewModel[];
  tradingDay: SectorAnalysisTradingDayResponse;
  pageStatus: SectorAnalysisPageStatusResponse;
  status: "READY" | "DELAYED";
}

export interface SectorMomentumHistoryPointViewModel {
  tradeDate: string;
  returnPct: number | null;
  strengthRank: number | null;
  calculableCount: number;
  totalCount: number;
  percentile: number | null;
}

export interface SectorMomentumHistoryViewModel {
  detail: SectorMomentumDetailResponse;
  points: SectorMomentumHistoryPointViewModel[];
  tradingDay: SectorAnalysisTradingDayResponse;
  pageStatus: SectorAnalysisPageStatusResponse;
  status: "READY" | "DELAYED";
}

export interface SectorMemberRowViewModel extends SectorMemberRowResponse {
  stockNameText: string;
  closeText: string;
  returnText: string;
  directionClass: "up" | "down" | "flat" | "muted";
}

export interface SectorMemberDetailViewModel extends Omit<SectorMemberDetailResponse, "rows"> {
  status: "READY";
  rows: SectorMemberRowViewModel[];
}

export type MemberViewState =
  | { kind: "idle" }
  | { kind: "loading"; key: string }
  | { kind: "ready"; key: string; data: SectorMemberDetailViewModel }
  | { kind: "empty"; key: string; message: string }
  | { kind: "error"; key: string; message: string; retryable: boolean };

export type MomentumViewState =
  | { kind: "loading"; meta?: SectorMomentumMetaViewModel }
  | {
      kind: "ready" | "delayed";
      meta: SectorMomentumMetaViewModel;
      ranking: SectorMomentumRankingViewModel;
      history: SectorMomentumHistoryViewModel;
      selectedCode: string;
    }
  | { kind: "empty"; meta: SectorMomentumMetaViewModel; message: string }
  | { kind: "error"; meta?: SectorMomentumMetaViewModel; message: string; retryable: boolean };
