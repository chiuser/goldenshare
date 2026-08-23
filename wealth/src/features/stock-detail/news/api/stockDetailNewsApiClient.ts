import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { StockDetailNewsApiResponse } from "./stockDetailNewsApiTypes";

export interface StockDetailNewsFetchOptions {
  signal?: AbortSignal;
}

export class StockDetailNewsApiError extends Error {
  code: string;

  constructor(message: string, code = "STOCK_DETAIL_NEWS_API_ERROR") {
    super(message);
    this.name = "StockDetailNewsApiError";
    this.code = code;
  }
}

export async function fetchStockDetailNews(
  params: {
    tsCode: string;
    startAt?: string;
    endAt?: string;
    limit?: number;
    debug?: 0 | 1;
  },
  options: StockDetailNewsFetchOptions = {},
): Promise<StockDetailNewsApiResponse> {
  const url = new URL("/api/v1/wealth/market/stock-detail/news", window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value));
  });
  const response = await wealthFetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  if (response.ok) return (await response.json()) as StockDetailNewsApiResponse;

  let message = `请求失败：${response.status}`;
  let code = `HTTP_${response.status}`;
  try {
    const payload = (await response.json()) as { code?: string; message?: string };
    if (payload.message) message = payload.message;
    if (payload.code) code = payload.code;
  } catch {
    // Keep the status-based fallback when the response is not JSON.
  }
  throw new StockDetailNewsApiError(message, code);
}
