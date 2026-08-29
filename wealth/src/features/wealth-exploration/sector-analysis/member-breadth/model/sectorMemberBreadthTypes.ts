export type SectorMemberBreadthScope =
  | "LEVEL_1"
  | "LEVEL_2"
  | "LEVEL_3"
  | "LEVEL_1_CHILDREN"
  | "LEVEL_2_CHILDREN";

export type SectorMemberBreadthUrlScope =
  | "level1"
  | "level2"
  | "level3"
  | "level1-children"
  | "level2-children";

export type SectorMemberBreadthDirection = "UP" | "DOWN";
export type SectorMemberBreadthUrlDirection = "up" | "down";
export type SectorMemberBreadthMetric = "MEMBER_COUNT" | "TURNOVER" | "MA_POSITION";
export type SectorMemberBreadthUrlMetric = "member-count" | "turnover" | "ma-position";
export type SectorMemberBreadthMaPeriod = 5 | 10 | 15 | 20 | 30 | 60;
export type SectorMemberBreadthHistoryRange = 20 | 30 | 60;
export type SectorMemberBreadthStatus = "READY" | "EMPTY" | "ERROR";
export type SectorMemberBreadthReason =
  | "SOURCE_MEMBER_EMPTY"
  | "MARKET_ROW_MISSING"
  | "PCT_CHANGE_MISSING"
  | "AMOUNT_MISSING"
  | "AMOUNT_NON_POSITIVE"
  | "ADJ_FACTOR_MISSING"
  | "ADJ_FACTOR_NON_POSITIVE"
  | "MA_HISTORY_INSUFFICIENT"
  | "MINIMUM_COUNT_NOT_MET"
  | "COVERAGE_NOT_MET";

export interface SectorMemberBreadthUrlState {
  market: "CN_A";
  tradeDate: string | null;
  scope: SectorMemberBreadthUrlScope;
  level1Code: string | null;
  level2Code: string | null;
  direction: SectorMemberBreadthUrlDirection;
  metric: SectorMemberBreadthUrlMetric;
  maPeriod: SectorMemberBreadthMaPeriod;
  historyRange: SectorMemberBreadthHistoryRange;
  sectorCode: string | null;
}

export interface SectorHierarchyNode {
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

export interface SectorTradeDateAvailability {
  tradeDate: string;
  availability: "COMPLETE" | "PARTIAL" | "MISSING";
  expectedSectorCount: number;
  validSectorCount: number;
}

export interface SectorMemberBreadthMetaViewModel {
  formulaKey: "sector-member-breadth";
  formulaVersion: 1;
  dateCoverageBasis: "INDUSTRY_DAILY";
  dateContext: {
    expectedTradeDate: string;
    defaultTradeDate: string | null;
    defaultStatus: "READY" | "DELAYED" | "EMPTY";
    displayText: string;
  };
  hierarchy: { hierarchyVersion: string; publishedAt: string; nodes: SectorHierarchyNode[] };
  coverageStartDate: string;
  coverageEndDate: string;
  tradeDates: SectorTradeDateAvailability[];
  scopes: SectorMemberBreadthScope[];
  directions: SectorMemberBreadthDirection[];
  metrics: SectorMemberBreadthMetric[];
  maPeriods: SectorMemberBreadthMaPeriod[];
  historyRanges: SectorMemberBreadthHistoryRange[];
  minimumCalculableCount: 5;
  minimumCoveragePct: 80;
  defaults: {
    scope: "LEVEL_1";
    direction: "UP";
    metric: "MEMBER_COUNT";
    maPeriod: 20;
    historyRange: 20;
  };
  level1Nodes: SectorHierarchyNode[];
  level2Nodes: SectorHierarchyNode[];
}

export interface SectorMemberBreadthRankingsRequest {
  market: "CN_A";
  tradeDate: string;
  scope: SectorMemberBreadthScope;
  level1Code?: string;
  level2Code?: string;
  direction: SectorMemberBreadthDirection;
  metric: SectorMemberBreadthMetric;
  maPeriod: SectorMemberBreadthMaPeriod;
  hierarchyVersion: string;
}

export interface SectorMemberBreadthDetailsRequest {
  market: "CN_A";
  tradeDate: string;
  sectorCode: string;
  direction: SectorMemberBreadthDirection;
  maPeriod: SectorMemberBreadthMaPeriod;
  historyRange: SectorMemberBreadthHistoryRange;
  hierarchyVersion: string;
}

export interface SectorMemberBreadthRankingRow {
  listPosition: number;
  rank: number | null;
  rankTotal: number | null;
  sectorCode: string;
  sectorName: string;
  industryLevel: 1 | 2 | 3;
  hierarchyPath: string;
  sourceMemberCount: number;
  calculableCount: number;
  coveragePct: number;
  metricValuePct: number | null;
  qualificationStatus: "ELIGIBLE" | "INELIGIBLE";
  reasonCodes: SectorMemberBreadthReason[];
  rankText: string;
  metricText: string;
  coverageText: string;
}

export interface SectorMemberBreadthRankingsViewModel {
  status: "READY";
  message: string | null;
  tradeDate: string;
  hierarchyVersion: string;
  scope: SectorMemberBreadthScope;
  parentSelection: { level1Code: string | null; level1Name: string | null; level2Code: string | null; level2Name: string | null };
  direction: SectorMemberBreadthDirection;
  metric: SectorMemberBreadthMetric;
  maPeriod: SectorMemberBreadthMaPeriod;
  totalSectorCount: number;
  eligibleSectorCount: number;
  ineligibleSectorCount: number;
  availability: { metric: SectorMemberBreadthMetric; calculableSectorCount: number; eligibleSectorCount: number; status: "AVAILABLE" | "PARTIAL" | "UNAVAILABLE"; reasonCodes: SectorMemberBreadthReason[] };
  defaultSelectedSectorCode: string | null;
  rows: SectorMemberBreadthRankingRow[];
}

export interface SectorMemberBreadthComposition {
  metric: SectorMemberBreadthMetric;
  sourceCount: number;
  calculableCount: number;
  coveragePct: number;
  eligible: boolean;
  positiveCount: number;
  neutralCount: number;
  negativeCount: number;
  positivePct: number | null;
  neutralPct: number | null;
  negativePct: number | null;
  reasonCodes: SectorMemberBreadthReason[];
}

export interface SectorMemberBreadthTrendPoint {
  tradeDate: string;
  memberPct: number | null;
  turnoverPct: number | null;
  maPositionPct: number | null;
  memberReasonCodes: SectorMemberBreadthReason[];
  turnoverReasonCodes: SectorMemberBreadthReason[];
  maPositionReasonCodes: SectorMemberBreadthReason[];
}

export interface SectorMemberBreadthMemberRow {
  stockName: string | null;
  stockCode: string;
  dailyPctChg: number | null;
  amountThousandYuan: number | null;
  amountContributionPct: number | null;
  maRelation: "ABOVE" | "EQUAL" | "BELOW" | null;
  maDistancePct: number | null;
  reasonCodes: SectorMemberBreadthReason[];
}

export interface SectorMemberBreadthDetailsViewModel {
  status: "READY";
  message: string | null;
  tradeDate: string;
  hierarchyVersion: string;
  sectorCode: string;
  sectorName: string;
  industryLevel: 1 | 2 | 3;
  hierarchyPath: string;
  direction: SectorMemberBreadthDirection;
  maPeriod: SectorMemberBreadthMaPeriod;
  historyRange: SectorMemberBreadthHistoryRange;
  compositions: SectorMemberBreadthComposition[];
  trend: SectorMemberBreadthTrendPoint[];
  members: SectorMemberBreadthMemberRow[];
}

export type SectorMemberBreadthRankingsAdapterResult =
  | { kind: "ready"; data: SectorMemberBreadthRankingsViewModel }
  | { kind: "empty"; message: string }
  | { kind: "error"; message: string; retryable: boolean };

export type SectorMemberBreadthDetailsAdapterResult =
  | { kind: "ready"; data: SectorMemberBreadthDetailsViewModel }
  | { kind: "empty"; message: string }
  | { kind: "error"; message: string; retryable: boolean };

export type SectorMemberBreadthDetailsState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; data: SectorMemberBreadthDetailsViewModel; pending: boolean }
  | { kind: "empty"; message: string }
  | { kind: "error"; message: string; retryable: boolean };

export type SectorMemberBreadthViewState =
  | { kind: "loading"; meta?: SectorMemberBreadthMetaViewModel }
  | { kind: "ready" | "delayed"; meta: SectorMemberBreadthMetaViewModel; rankings: SectorMemberBreadthRankingsViewModel; details: SectorMemberBreadthDetailsState; pending: boolean }
  | { kind: "empty"; meta?: SectorMemberBreadthMetaViewModel; message: string }
  | { kind: "error"; meta?: SectorMemberBreadthMetaViewModel; message: string; retryable: boolean };
