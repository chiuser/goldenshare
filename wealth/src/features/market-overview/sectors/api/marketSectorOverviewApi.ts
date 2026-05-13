import type { DataStatus, MarketDirection } from "../../../../shared/model/market";

export interface MarketSectorOverviewRequest {
  market?: "CN_A";
  tradeDate?: string;
  debug?: 0 | 1;
}

export interface MarketSectorOverviewFetchOptions {
  signal?: AbortSignal;
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

export interface MarketSectorOverviewResponse {
  tradingDay: {
    tradeDate: string;
    prevTradeDate?: string | null;
    market: "CN_A";
    isTradingDay: boolean;
    sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
    timezone: "Asia/Shanghai";
  };
  pageStatus: {
    status: DataStatus;
    displayText: string;
    asOfTime?: string | null;
  };
  sectorOverview: {
    tradeDate: string;
    status: DataStatus;
    columns: Array<{
      columnKey: string;
      title: string;
      tone: "UP" | "DOWN" | "NEUTRAL";
      metricLabel: string;
      rows: Array<{
        rank: number;
        subject: {
          subjectType: "sector";
          subjectCode: string;
          subjectName?: string | null;
          sectorType: "INDUSTRY" | "CONCEPT" | "REGION";
        };
        metric: {
          value?: number | null;
          displayText: string;
          unit?: "%" | null;
          direction: MarketDirection;
        };
        leadingStock?: {
          stockCode?: string | null;
          stockName?: string | null;
          changePct?: number | null;
        } | null;
      }>;
    }>;
    heatMapItems: Array<{
      subject: {
        subjectType: "sector";
        subjectCode: string;
        subjectName?: string | null;
        sectorType: "INDUSTRY" | "CONCEPT" | "REGION";
      };
      changePct?: number | null;
      direction: MarketDirection;
      riseStockCount?: number | null;
      fallStockCount?: number | null;
      leadingStock?: {
        stockCode?: string | null;
        stockName?: string | null;
        changePct?: number | null;
      } | null;
    }>;
  };
  debugInfo?: SectorOverviewDebugInfo | null;
}

export class MarketSectorOverviewApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_SECTOR_OVERVIEW_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildSectorOverviewUrl(params: MarketSectorOverviewRequest): string {
  const url = new URL("/api/v1/wealth/market/sector-overview", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketSectorOverview(
  params: MarketSectorOverviewRequest = {},
  options: MarketSectorOverviewFetchOptions = {},
): Promise<MarketSectorOverviewResponse> {
  const response = await fetch(buildSectorOverviewUrl(params), {
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
      // ignore parse failure and keep default message
    }
    throw new MarketSectorOverviewApiError(message, code);
  }
  return (await response.json()) as MarketSectorOverviewResponse;
}
