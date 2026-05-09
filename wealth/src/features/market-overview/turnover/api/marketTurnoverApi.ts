import type { DataStatus } from "../../../../shared/model/market";

export interface MarketTurnoverRequest {
  market?: "CN_A";
  tradeDate?: string;
  debug?: 0 | 1;
}

export interface MarketTurnoverFetchOptions {
  signal?: AbortSignal;
}

export interface TurnoverDebugInfo {
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

export interface MarketTurnoverResponse {
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
  turnover: {
    tradeDate: string;
    metrics: {
      todayAmount?: number | null;
      prevAmount?: number | null;
      amountDelta?: number | null;
      amountDeltaPct?: number | null;
      avg5dAmount?: number | null;
      avg20dAmount?: number | null;
      unit: "thousand_yuan";
    };
    intradayCumulative: Array<{ time: string; cumAmount?: number | null }>;
    historyByRange: {
      oneMonth: Array<{ tradeDate: string; amount?: number | null }>;
      threeMonth: Array<{ tradeDate: string; amount?: number | null }>;
    };
  };
  debugInfo?: TurnoverDebugInfo | null;
}

export class MarketTurnoverApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_TURNOVER_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildTurnoverUrl(params: MarketTurnoverRequest): string {
  const url = new URL("/api/v1/wealth/market/turnover", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketTurnover(
  params: MarketTurnoverRequest = {},
  options: MarketTurnoverFetchOptions = {},
): Promise<MarketTurnoverResponse> {
  const response = await fetch(buildTurnoverUrl(params), {
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
    throw new MarketTurnoverApiError(message, code);
  }
  return (await response.json()) as MarketTurnoverResponse;
}
