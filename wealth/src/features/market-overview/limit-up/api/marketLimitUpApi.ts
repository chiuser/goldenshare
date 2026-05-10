import type { DataStatus, MarketDirection } from "../../../../shared/model/market";

export interface MarketLimitUpRequest {
  market?: "CN_A";
  tradeDate?: string;
  debug?: 0 | 1;
}

export interface MarketLimitUpFetchOptions {
  signal?: AbortSignal;
}

export interface MarketLimitUpResponse {
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
  limitUp: {
    tradeDate: string;
    summaryCards: Array<{
      key:
        | "limitUpCount"
        | "limitDownCount"
        | "brokenLimitCount"
        | "sealingRate"
        | "streakCount"
        | "maxBoard"
        | "skyToFloorCount"
        | "floorToSkyCount";
      label: string;
      value: string | number | null;
      unit?: string | null;
      direction: MarketDirection;
      subText?: string | null;
    }>;
    todayStructure: {
      tradeDate: string;
      selectedSectorCode: string;
      selectedStockCode: string;
      sectors: Array<{
        sectorCode: string;
        sectorName: string;
        sectorType: "CONCEPT" | "INDUSTRY" | "REGION" | "OTHER";
        limitUpCount: number;
      }>;
      leaderStocks: Record<
        string,
        Array<{
          stockCode: string;
          stockName?: string | null;
          latestPrice?: number | null;
          changePct?: number | null;
          rank: number;
          streakLabel: string;
          recentLimitText: string;
          firstLimitTime: string;
          openTimes: number;
          sealedAmountDisplayText: string;
        }>
      >;
    };
    yesterdayStructure: {
      tradeDate: string;
      selectedSectorCode: string;
      selectedStockCode: string;
      sectors: Array<{
        sectorCode: string;
        sectorName: string;
        sectorType: "CONCEPT" | "INDUSTRY" | "REGION" | "OTHER";
        limitUpCount: number;
      }>;
      leaderStocks: Record<
        string,
        Array<{
          stockCode: string;
          stockName?: string | null;
          latestPrice?: number | null;
          changePct?: number | null;
          rank: number;
          streakLabel: string;
          recentLimitText: string;
          firstLimitTime: string;
          openTimes: number;
          sealedAmountDisplayText: string;
        }>
      >;
    };
    historyPoints: {
      oneMonth: Array<{
        tradeDate: string;
        limitUpCount: number;
        limitDownCount: number;
      }>;
      threeMonth: Array<{
        tradeDate: string;
        limitUpCount: number;
        limitDownCount: number;
      }>;
    };
  };
  debugInfo?: {
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
  } | null;
}

export interface LimitUpDebugInfo {
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

export class MarketLimitUpApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_LIMIT_UP_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildLimitUpUrl(params: MarketLimitUpRequest): string {
  const url = new URL("/api/v1/wealth/market/limit-up/summary", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketLimitUp(
  params: MarketLimitUpRequest = {},
  options: MarketLimitUpFetchOptions = {},
): Promise<MarketLimitUpResponse> {
  const response = await fetch(buildLimitUpUrl(params), {
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
    throw new MarketLimitUpApiError(message, code);
  }
  return (await response.json()) as MarketLimitUpResponse;
}
