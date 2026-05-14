import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus } from "../../../../shared/model/market";

export interface MarketNewsRequest {
  market?: "CN_A";
  debug?: 0 | 1;
}

export interface MarketNewsFetchOptions {
  signal?: AbortSignal;
}

export interface MarketNewsDebugInfo {
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

export interface NewsPanelItemResponse {
  newsId: string;
  publishTime: string;
  displayTime: string;
  title: string;
  category: "market" | "stock";
  source?: string | null;
  subject?: {
    subjectType: "stock";
    subjectCode: string;
    subjectName?: string | null;
  } | null;
  priority?: number | null;
  url?: string | null;
  clickable: false;
}

export interface NewsListPanelResponse {
  windowStartAt: string;
  windowEndAt: string;
  panelKey: "newsBriefs" | "stockNews";
  visibleItemCount: number;
  updatedAt: string;
  items: NewsPanelItemResponse[];
  sortRule: "publishTime_desc_priority_desc";
  clickablePolicy: "disabled";
}

export interface MarketNewsBaseResponse {
  newsWindow: {
    market: "CN_A";
    startAt: string;
    endAt: string;
    timezone: "Asia/Shanghai";
  };
  pageStatus: {
    status: DataStatus;
    displayText: string;
    asOfTime?: string | null;
  };
  debugInfo?: MarketNewsDebugInfo | null;
}

export interface MarketNewsBriefsResponse extends MarketNewsBaseResponse {
  newsBriefs: NewsListPanelResponse;
}

export interface StockNewsResponse extends MarketNewsBaseResponse {
  stockNews: NewsListPanelResponse;
}

export class MarketNewsApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_NEWS_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildNewsUrl(path: "/briefs" | "/stocks", params: MarketNewsRequest): string {
  const url = new URL(`/api/v1/wealth/market/news${path}`, window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

async function fetchJson<T>(path: "/briefs" | "/stocks", params: MarketNewsRequest, options: MarketNewsFetchOptions): Promise<T> {
  const response = await wealthFetch(buildNewsUrl(path, params), {
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
      // keep the default HTTP error message
    }
    throw new MarketNewsApiError(message, code);
  }
  return (await response.json()) as T;
}

export function fetchMarketNewsBriefs(
  params: MarketNewsRequest = {},
  options: MarketNewsFetchOptions = {},
): Promise<MarketNewsBriefsResponse> {
  return fetchJson<MarketNewsBriefsResponse>("/briefs", params, options);
}

export function fetchStockNews(
  params: MarketNewsRequest = {},
  options: MarketNewsFetchOptions = {},
): Promise<StockNewsResponse> {
  return fetchJson<StockNewsResponse>("/stocks", params, options);
}
