import type { DataStatus, MarketDirection } from "../../../../shared/model/market";

export interface MarketMajorIndicesRequest {
  market?: "CN_A";
  tradeDate?: string;
  debug?: 0 | 1;
}

export interface MarketMajorIndicesFetchOptions {
  signal?: AbortSignal;
}

export interface MarketMajorIndicesResponse {
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
  majorIndices: {
    definition: {
      definitionKey: string;
      version: string;
      fixedCount: 10;
    };
    rows: Array<{
      subject: {
        subjectType: "index";
        subjectCode: string;
        subjectName?: string | null;
      };
      point?: number | null;
      change?: number | null;
      changePct?: number | null;
      amount?: number | null;
      direction: MarketDirection;
    }>;
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

export class MarketMajorIndicesApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_MAJOR_INDICES_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildMajorIndicesUrl(params: MarketMajorIndicesRequest): string {
  const url = new URL("/api/v1/wealth/market/major-indices", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchMarketMajorIndices(
  params: MarketMajorIndicesRequest = {},
  options: MarketMajorIndicesFetchOptions = {},
): Promise<MarketMajorIndicesResponse> {
  const response = await fetch(buildMajorIndicesUrl(params), {
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
    throw new MarketMajorIndicesApiError(message, code);
  }
  return (await response.json()) as MarketMajorIndicesResponse;
}

