import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus, MarketDirection } from "../../../../shared/model/market";

export type SectorOverviewView = "INDUSTRY" | "CONCEPT" | "REGION";
export type IndustryRankMetric = "CHANGE_PCT" | "MAIN_NET_INFLOW" | "UP_COUNT";
export type ConceptRankMetric = "HEAT_SCORE" | "HEAT_DELTA_1D" | "CHANGE_PCT" | "MAIN_NET_INFLOW";
export type RegionRankMetric = "CHANGE_PCT" | "MAIN_NET_INFLOW" | "UP_COUNT";
export type SectorRankMetric = IndustryRankMetric | ConceptRankMetric | RegionRankMetric;
export type HeatStatus = "VALID" | "INVALID" | "UNKNOWN";
export type HeatLevel = "BOILING" | "HOT" | "ACTIVE" | "NONE";
export type HeatTrend = "HEATING" | "STABLE" | "COOLING" | "UNKNOWN";

export interface MarketSectorOverviewRequest {
  market?: "CN_A";
  tradeDate?: string;
  view?: SectorOverviewView;
  industryRankMetric?: IndustryRankMetric;
  selectedIndustryCode?: string;
  conceptRankMetric?: ConceptRankMetric;
  selectedConceptCode?: string;
  regionRankMetric?: RegionRankMetric;
  selectedRegionCode?: string;
  debug?: 0 | 1;
}

export interface SectorOverviewDebugInfo {
  modules: Array<{
    moduleKey: string;
    expectedTradeDate: string;
    observedTradeDate?: string | null;
    lagDays?: number | null;
    status: DataStatus;
    note?: string | null;
  }>;
  exceptions: Array<{
    module: string;
    code: string;
    severity: "info" | "warn" | "error";
    message: string;
    details?: Record<string, string | number | null> | null;
  }>;
}

export interface MetricValue {
  value: number | null;
  displayText: string;
  direction: MarketDirection;
}

export interface SectorLeaderStock {
  stockCode: string | null;
  stockName: string | null;
  changePct: number | null;
}

export interface SectorMemberStock {
  stockCode: string;
  stockName: string | null;
  changePct: number | null;
  direction: MarketDirection;
}

export interface ConceptHeat {
  heatStatus: Exclude<HeatStatus, "UNKNOWN">;
  invalidReason: "MEMBER_COUNT_LOW" | "QUOTE_ELIGIBLE_COUNT_ZERO" | "QUOTE_COVERAGE_LOW" | "HISTORY_INSUFFICIENT" | "FEATURE_MISSING" | null;
  heatScore: number | null;
  heatLevel: HeatLevel;
  heatDelta1d: number | null;
  heatTrend: HeatTrend;
  heatRank: number | null;
  scoreVersion: string;
  tradeDate: string;
  calculatedAt: string;
}

export interface ConceptHeatPoint {
  tradeDate: string;
  heatScore: number | null;
  heatRank: number | null;
  heatLevel: HeatLevel;
}

export interface SectorMetrics {
  changePct: number | null;
  upCount: number | null;
  downCount: number | null;
  sourceMemberCount: number;
  memberCount: number;
  suspendedCount: number;
  quoteEligibleCount: number;
  validQuoteCount: number;
  missingQuoteCount: number;
  mainNetInflow: number | null;
  turnoverAmount: number | null;
  quoteCoverage: number | null;
}

interface SectorDetailBase {
  sectorCode: string;
  sectorName: string;
  metrics: SectorMetrics;
  leader: SectorLeaderStock | null;
  members: SectorMemberStock[];
}

export interface IndustryDetail extends SectorDetailBase {
  sectorType: "INDUSTRY";
  hierarchyPath?: string | null;
}

export interface ConceptDetail extends SectorDetailBase {
  sectorType: "CONCEPT";
  heat?: ConceptHeat | null;
  heatHistory?: ConceptHeatPoint[];
}

export interface RegionDetail extends SectorDetailBase {
  sectorType: "REGION";
}

export interface IndustryRankItem {
  rank: number;
  sectorCode: string;
  sectorName: string;
  industryLevel: 1 | 2 | 3;
  primaryMetric: MetricValue;
  leader: SectorLeaderStock | null;
  selected: boolean;
}

export interface ConceptRankItem {
  rank: number;
  sectorCode: string;
  sectorName: string;
  changePct: MetricValue;
  mainNetInflow: MetricValue;
  leader: SectorLeaderStock | null;
  heatStatus: HeatStatus;
  heatLevel: HeatLevel;
  heatTrend: HeatTrend;
  heatScore: MetricValue;
  heatDelta1d: MetricValue;
  selected: boolean;
}

export interface RegionRankItem {
  rank: number;
  sectorCode: string;
  sectorName: string;
  changePct: MetricValue;
  mainNetInflow: MetricValue;
  memberCount: number | null;
  upCount: number | null;
  leader: SectorLeaderStock | null;
  selected: boolean;
}

export interface IndustryWorkspace {
  rankMetric: IndustryRankMetric;
  selection: {
    level1Code: string | null;
    level2Code: string | null;
    level3Code: string | null;
    detailSectorCode: string | null;
  };
  columns: Array<{
    level: 1 | 2 | 3;
    parentSectorCode: string | null;
    rows: IndustryRankItem[];
  }>;
  detail: IndustryDetail | null;
}

export interface ConceptWorkspace {
  rankMetric: ConceptRankMetric;
  selectedConceptCode: string | null;
  rows: ConceptRankItem[];
  detail: ConceptDetail | null;
}

export interface RegionWorkspace {
  rankMetric: RegionRankMetric;
  selectedRegionCode: string | null;
  rows: RegionRankItem[];
  detail: RegionDetail | null;
}

interface SectorOverviewPanelBase {
  tradeDate: string;
  status: DataStatus;
  asOf: string;
}

export type IndustrySectorOverviewPanel = SectorOverviewPanelBase & { view: "INDUSTRY"; industry: IndustryWorkspace };
export type ConceptSectorOverviewPanel = SectorOverviewPanelBase & { view: "CONCEPT"; concept: ConceptWorkspace };
export type RegionSectorOverviewPanel = SectorOverviewPanelBase & { view: "REGION"; region: RegionWorkspace };
export type SectorOverviewPanelData = IndustrySectorOverviewPanel | ConceptSectorOverviewPanel | RegionSectorOverviewPanel;

export interface MarketSectorOverviewResponse {
  tradingDay: {
    tradeDate: string;
    prevTradeDate?: string | null;
    market: "CN_A";
    isTradingDay: boolean;
    sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
    timezone: "Asia/Shanghai";
  };
  pageStatus: { status: DataStatus; displayText: string; asOfTime?: string | null };
  sectorOverview: SectorOverviewPanelData;
  debugInfo?: SectorOverviewDebugInfo | null;
}

export class MarketSectorOverviewApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code = "MARKET_SECTOR_OVERVIEW_API_ERROR", status = 0) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function buildSectorOverviewUrl(params: MarketSectorOverviewRequest): string {
  const url = new URL("/api/v1/wealth/market/sector-overview", window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (typeof value !== "undefined") url.searchParams.set(key, String(value));
  });
  return url.toString();
}

export async function fetchMarketSectorOverview(
  params: MarketSectorOverviewRequest = {},
  options: { signal?: AbortSignal } = {},
): Promise<MarketSectorOverviewResponse> {
  const response = await wealthFetch(buildSectorOverviewUrl(params), {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    let code = `HTTP_${response.status}`;
    try {
      const payload = (await response.json()) as { code?: string; message?: string };
      if (payload.message) message = payload.message;
      if (payload.code) code = payload.code;
    } catch {
      // Keep the status-based fallback when the response is not JSON.
    }
    throw new MarketSectorOverviewApiError(message, code, response.status);
  }
  return (await response.json()) as MarketSectorOverviewResponse;
}
