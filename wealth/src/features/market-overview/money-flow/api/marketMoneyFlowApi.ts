import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus } from "../../../../shared/model/market";

export interface MarketMoneyFlowRequest {
  market?: "CN_A";
  tradeDate?: string;
  debug?: 0 | 1;
}

export interface MarketMoneyFlowFetchOptions {
  signal?: AbortSignal;
}

export interface MoneyFlowDebugInfo {
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

export interface MarketMoneyFlowResponse {
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
  moneyFlow: {
    tradeDate: string;
    metrics: {
      todayNetAmount?: number | null;
      prevNetAmount?: number | null;
      unit: "yuan";
    };
    byOrderSize: {
      elg: { amount?: number | null; rate?: number | null };
      lg: { amount?: number | null; rate?: number | null };
      md: { amount?: number | null; rate?: number | null };
      sm: { amount?: number | null; rate?: number | null };
    };
    historyByRange: {
      oneMonth: Array<{ tradeDate: string; netAmount?: number | null }>;
      threeMonth: Array<{ tradeDate: string; netAmount?: number | null }>;
    };
  };
  debugInfo?: MoneyFlowDebugInfo | null;
}

export class MarketMoneyFlowApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_MONEY_FLOW_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildMoneyFlowUrl(params: MarketMoneyFlowRequest): string {
  const url = new URL("/api/v1/wealth/market/money-flow", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketMoneyFlow(
  params: MarketMoneyFlowRequest = {},
  options: MarketMoneyFlowFetchOptions = {},
): Promise<MarketMoneyFlowResponse> {
  const response = await wealthFetch(buildMoneyFlowUrl(params), {
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
    throw new MarketMoneyFlowApiError(message, code);
  }
  return (await response.json()) as MarketMoneyFlowResponse;
}
