import type { DataStatus, MarketDirection } from "../../../../shared/model/market";

export interface MarketSummaryRequest {
  market?: "CN_A";
  tradeDate?: string;
  debug?: 0 | 1;
}

export interface MarketSummaryFetchOptions {
  signal?: AbortSignal;
}

export interface TradingDay {
  tradeDate: string;
  prevTradeDate?: string | null;
  market: "CN_A";
  isTradingDay: boolean;
  sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
  timezone: "Asia/Shanghai";
}

export interface PageStatus {
  status: DataStatus;
  displayText: string;
  asOfTime?: string | null;
}

export interface MarketSummaryCard {
  cardKey: string;
  label: string;
  value?: string | null;
  subText?: string | null;
  direction?: MarketDirection | null;
}

export interface MarketSummaryPayload {
  definition: {
    definitionKey: string;
    version: string;
    cardCount: 5 | 6;
    textPosition: "BOTTOM_FIXED";
    layoutVariant: "FIVE_SINGLE_ROW" | "SIX_TWO_ROWS";
  };
  cards: MarketSummaryCard[];
  textCard: {
    title: string;
    content: string;
    templateKey: string;
  };
}

export interface SummaryDebugInfo {
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

export interface MarketSummaryResponse {
  tradingDay: TradingDay;
  pageStatus: PageStatus;
  marketSummary: MarketSummaryPayload;
  debugInfo?: SummaryDebugInfo | null;
}

export class MarketSummaryApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_SUMMARY_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildSummaryUrl(params: MarketSummaryRequest): string {
  const url = new URL("/api/v1/wealth/market/summary", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketSummary(
  params: MarketSummaryRequest = {},
  options: MarketSummaryFetchOptions = {},
): Promise<MarketSummaryResponse> {
  const response = await fetch(buildSummaryUrl(params), {
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
    throw new MarketSummaryApiError(message, code);
  }
  return (await response.json()) as MarketSummaryResponse;
}
