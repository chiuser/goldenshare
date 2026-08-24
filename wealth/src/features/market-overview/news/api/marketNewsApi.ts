import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus } from "../../../../shared/model/market";
import type { NewsReaderMode } from "../../../../shared/ui/news-reader/newsReaderTypes";

export type { NewsReaderMode } from "../../../../shared/ui/news-reader/newsReaderTypes";
export type NewsContentSource = "news" | "major_news";

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
  contentSource: NewsContentSource;
  publishTime: string;
  displayTime: string;
  title: string;
  category: "brief" | "communication";
  source?: string | null;
  readerMode: NewsReaderMode;
  clickable: true;
}

export interface NewsListPanelResponse {
  windowStartAt: string;
  windowEndAt: string;
  panelKey: "newsBriefs" | "newsCommunications";
  visibleItemCount: number;
  updatedAt: string;
  items: NewsPanelItemResponse[];
  sortRule: "publishTime_desc";
  clickablePolicy: "reader";
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

export interface NewsCommunicationsResponse extends MarketNewsBaseResponse {
  newsCommunications: NewsListPanelResponse;
}

export class MarketNewsApiError extends Error {
  code: string;

  constructor(message: string, code = "MARKET_NEWS_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildNewsUrl(path: "/briefs" | "/communications", params: MarketNewsRequest): string {
  const url = new URL(`/api/v1/wealth/market/news${path}`, window.location.origin);
  if (params.market) url.searchParams.set("market", params.market);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

async function fetchJson<T>(
  path: "/briefs" | "/communications",
  params: MarketNewsRequest,
  options: MarketNewsFetchOptions,
): Promise<T> {
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

export function fetchNewsCommunications(
  params: MarketNewsRequest = {},
  options: MarketNewsFetchOptions = {},
): Promise<NewsCommunicationsResponse> {
  return fetchJson<NewsCommunicationsResponse>("/communications", params, options);
}
