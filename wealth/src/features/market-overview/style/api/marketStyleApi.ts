import type { DataStatus, MarketDirection } from "../../../../shared/model/market";

export interface MarketStyleRequest {
  market?: "CN_A";
  tradeDate?: string;
  debug?: 0 | 1;
}

export interface MarketStyleFetchOptions {
  signal?: AbortSignal;
}

export interface StyleDebugInfo {
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

export interface MarketStyleResponse {
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
  style: {
    definition: {
      definitionKey: string;
      version: string;
      fixedCardCount: 3;
    };
    cards: Array<{
      cardKey: "largeCap" | "smallCap" | "median";
      label: string;
      valuePct?: number | null;
      sourceText: string;
      direction: MarketDirection;
    }>;
    historyByRange: {
      oneMonth: Array<{ tradeDate: string; largePct?: number | null; smallPct?: number | null; medianPct?: number | null }>;
      threeMonth: Array<{ tradeDate: string; largePct?: number | null; smallPct?: number | null; medianPct?: number | null }>;
    };
  };
  debugInfo?: StyleDebugInfo | null;
}

export class MarketStyleApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_STYLE_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildStyleUrl(params: MarketStyleRequest): string {
  const url = new URL("/api/v1/wealth/market/style", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketStyle(
  params: MarketStyleRequest = {},
  options: MarketStyleFetchOptions = {},
): Promise<MarketStyleResponse> {
  const response = await fetch(buildStyleUrl(params), {
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
    throw new MarketStyleApiError(message, code);
  }
  return (await response.json()) as MarketStyleResponse;
}
