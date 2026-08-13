import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus, MarketDirection } from "../../../../shared/model/market";

export type SectorOverviewView = "INDUSTRY" | "CONCEPT" | "REGION";
export type IndustryRankMetric = "CHANGE_PCT" | "MAIN_NET_INFLOW" | "UP_COUNT";
export type ConceptRankMetric = "HEAT_SCORE" | "HEAT_DELTA_1D" | "CHANGE_PCT" | "MAIN_NET_INFLOW";
export type RegionRankMetric = "CHANGE_PCT" | "MAIN_NET_INFLOW" | "UP_COUNT";
export type SectorRankMetric = IndustryRankMetric | ConceptRankMetric | RegionRankMetric;

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

export interface ConceptHeat {
  heatStatus: "VALID" | "INVALID";
  invalidReason: "MEMBER_COUNT_LOW" | "QUOTE_ELIGIBLE_COUNT_ZERO" | "QUOTE_COVERAGE_LOW" | "HISTORY_INSUFFICIENT" | "FEATURE_MISSING" | null;
  heatScore: number | null;
  heatLevel: "BOILING" | "HOT" | "ACTIVE" | "NONE";
  heatDelta1d: number | null;
  heatTrend: "HEATING" | "STABLE" | "COOLING" | "UNKNOWN";
  heatRank: number | null;
  scoreVersion: string;
  tradeDate: string;
  calculatedAt: string;
}

export interface SectorRankItem {
  rank: number;
  sectorCode: string;
  sectorName: string;
  level?: 1 | 2 | 3;
  primaryMetric: MetricValue;
  leader: SectorLeaderStock | null;
  heat?: ConceptHeat | null;
  selected: boolean;
}

export interface SectorDetail {
  sectorCode: string;
  sectorName: string;
  sectorType: SectorOverviewView;
  hierarchyPath?: string | null;
  metrics: {
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
  };
  heat?: ConceptHeat | null;
  heatHistory?: Array<{
    tradeDate: string;
    heatScore: number | null;
    heatRank: number | null;
    heatLevel: "BOILING" | "HOT" | "ACTIVE" | "NONE";
  }>;
  leader: SectorLeaderStock | null;
  members: Array<{
    stockCode: string;
    stockName: string | null;
    changePct: number | null;
    direction: MarketDirection;
  }>;
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
    rows: SectorRankItem[];
  }>;
  detail: SectorDetail | null;
}

export interface ConceptWorkspace {
  rankMetric: ConceptRankMetric;
  selectedConceptCode: string | null;
  rows: SectorRankItem[];
  detail: SectorDetail | null;
}

export interface RegionWorkspace {
  rankMetric: RegionRankMetric;
  selectedRegionCode: string | null;
  rows: SectorRankItem[];
  detail: SectorDetail | null;
}

interface SectorOverviewPanelBase {
  tradeDate: string;
  status: DataStatus;
  asOf: string;
}

export type SectorOverviewPanelData =
  | (SectorOverviewPanelBase & { view: "INDUSTRY"; industry: IndustryWorkspace })
  | (SectorOverviewPanelBase & { view: "CONCEPT"; concept: ConceptWorkspace })
  | (SectorOverviewPanelBase & { view: "REGION"; region: RegionWorkspace });

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
