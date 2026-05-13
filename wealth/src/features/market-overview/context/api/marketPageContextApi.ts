export interface MarketPageContextRequest {
  market?: "CN_A";
  tradeDate?: string;
}

export interface MarketPageContextResponse {
  pageContext: {
    market: "CN_A";
    tradeDate: string;
    prevTradeDate?: string | null;
    isTradingDay: boolean;
    sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
    timezone: "Asia/Shanghai";
    generatedAt: string;
    source: "explicit" | "default";
  };
}

export class MarketPageContextApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_PAGE_CONTEXT_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildMarketPageContextUrl(params: MarketPageContextRequest): string {
  const url = new URL("/api/v1/wealth/market/context", window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (params.tradeDate) url.searchParams.set("tradeDate", params.tradeDate);
  return url.toString();
}

export async function fetchMarketPageContext(
  params: MarketPageContextRequest = {},
  options: { signal?: AbortSignal } = {},
): Promise<MarketPageContextResponse> {
  const response = await fetch(buildMarketPageContextUrl(params), {
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
    throw new MarketPageContextApiError(message, code);
  }
  return (await response.json()) as MarketPageContextResponse;
}
