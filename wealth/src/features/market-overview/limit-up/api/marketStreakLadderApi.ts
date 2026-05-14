import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus } from "../../../../shared/model/market";

export interface MarketStreakLadderRequest {
  market?: "CN_A";
  tradeDate?: string;
  debug?: 0 | 1;
}

export interface MarketStreakLadderFetchOptions {
  signal?: AbortSignal;
}

export interface MarketStreakLadderStockResponse {
  stockName?: string | null;
  stockCode: string;
  latestPrice?: number | null;
  changePct?: number | null;
  sectorName?: string | null;
  limitAmount: number | null;
  limitAmountDisplayText: string;
  limitAmountLabel: "封单金额" | "板上成交金额";
  streakText: string;
  openTimes?: number | null;
  firstLimitTime?: string | null;
  currentStreakLevel: number;
  advanced: boolean;
  quoteStatus: "READY" | "SUSPENDED" | "MISSING";
}

export interface MarketStreakLadderResponse {
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
  streakLadderV5: {
    tradeDate: string;
    prevTradeDate: string;
    highestStreakLevel: number;
    aboveFive: MarketStreakLadderStockResponse[];
    promotions: Record<
      number,
      {
        previousLabel: string;
        currentLabel: string;
        previousStocks: MarketStreakLadderStockResponse[];
        currentStocks: MarketStreakLadderStockResponse[];
      }
    >;
    firstBoard: MarketStreakLadderStockResponse[];
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

export interface StreakLadderDebugInfo {
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

export class MarketStreakLadderApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_STREAK_LADDER_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildStreakLadderUrl(params: MarketStreakLadderRequest): string {
  const url = new URL("/api/v1/wealth/market/streak-ladder", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketStreakLadder(
  params: MarketStreakLadderRequest = {},
  options: MarketStreakLadderFetchOptions = {},
): Promise<MarketStreakLadderResponse> {
  const response = await wealthFetch(buildStreakLadderUrl(params), {
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
      // ignore
    }
    throw new MarketStreakLadderApiError(message, code);
  }
  return (await response.json()) as MarketStreakLadderResponse;
}
