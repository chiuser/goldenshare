import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus } from "../../../../shared/model/market";

export interface MarketBreadthRequest {
  market?: "CN_A";
  tradeDate?: string;
  debug?: 0 | 1;
}

export interface MarketBreadthFetchOptions {
  signal?: AbortSignal;
}

export interface BreadthDebugInfo {
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

export interface MarketBreadthResponse {
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
  breadth: {
    tradeDate: string;
    metrics: {
      upCount: number;
      downCount: number;
      flatCount: number;
      redRate: number;
    };
    historyByRange: {
      "1m": Array<{ tradeDate: string; upCount: number; downCount: number }>;
      "3m": Array<{ tradeDate: string; upCount: number; downCount: number }>;
    };
  };
  debugInfo?: BreadthDebugInfo | null;
}

export class MarketBreadthApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_BREADTH_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildBreadthUrl(params: MarketBreadthRequest): string {
  const url = new URL("/api/v1/wealth/market/breadth", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketBreadth(
  params: MarketBreadthRequest = {},
  options: MarketBreadthFetchOptions = {},
): Promise<MarketBreadthResponse> {
  const response = await wealthFetch(buildBreadthUrl(params), {
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
    throw new MarketBreadthApiError(message, code);
  }
  return (await response.json()) as MarketBreadthResponse;
}
