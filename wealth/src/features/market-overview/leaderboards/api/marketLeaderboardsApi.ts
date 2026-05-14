import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus, MarketDirection } from "../../../../shared/model/market";

export interface MarketLeaderboardsRequest {
  market?: "CN_A";
  tradeDate?: string;
  limit?: number;
  debug?: 0 | 1;
}

export interface MarketLeaderboardsFetchOptions {
  signal?: AbortSignal;
}

export interface LeaderboardsDebugInfo {
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

export interface MarketLeaderboardsResponse {
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
  definitions: Array<{
    boardKey: "gainers" | "losers" | "amount" | "turnover" | "volumeRatio" | "popularity" | "surge";
    boardLabel: string;
  }>;
  boards: Array<{
    boardKey: "gainers" | "losers" | "amount" | "turnover" | "volumeRatio" | "popularity" | "surge";
    boardLabel: string;
    status: DataStatus;
    expectedTradeDate: string;
    observedTradeDate?: string | null;
    lagDays?: number | null;
    rows: Array<{
      rank: number;
      subject: {
        subjectType: "stock";
        subjectCode: string;
        subjectName?: string | null;
      };
      metrics: {
        latestPrice?: number | null;
        changePct?: number | null;
        turnoverRate?: number | null;
        volumeRatio?: number | null;
        volume?: number | null;
        amount?: number | null;
        direction: MarketDirection;
      };
    }>;
  }>;
  debugInfo?: LeaderboardsDebugInfo | null;
}

export class MarketLeaderboardsApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_LEADERBOARDS_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildLeaderboardsUrl(params: MarketLeaderboardsRequest): string {
  const url = new URL("/api/v1/wealth/market/leaderboards", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.limit !== "undefined") url.searchParams.set("limit", String(params.limit));
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketLeaderboards(
  params: MarketLeaderboardsRequest = {},
  options: MarketLeaderboardsFetchOptions = {},
): Promise<MarketLeaderboardsResponse> {
  const response = await wealthFetch(buildLeaderboardsUrl(params), {
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
    throw new MarketLeaderboardsApiError(message, code);
  }
  return (await response.json()) as MarketLeaderboardsResponse;
}
