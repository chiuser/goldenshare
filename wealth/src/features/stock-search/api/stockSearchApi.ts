import { wealthFetch } from "../../../shared/api/wealthApiClient";
import type { StockSearchResponseDto } from "./stockSearchApiTypes";

export const DEFAULT_STOCK_SEARCH_LIMIT = 8;

export class StockSearchApiError extends Error {
  code: string;

  constructor(message: string, code = "STOCK_SEARCH_API_ERROR") {
    super(message);
    this.code = code;
  }
}

export function buildStockSearchUrl(
  keyword: string,
  limit = DEFAULT_STOCK_SEARCH_LIMIT,
): string {
  const url = new URL("/api/v1/wealth/market/stock-search", window.location.origin);
  url.searchParams.set("keyword", keyword);
  url.searchParams.set("limit", String(limit));
  return url.toString();
}

export async function fetchStockSearch(
  keyword: string,
  options: { signal?: AbortSignal; limit?: number } = {},
): Promise<StockSearchResponseDto> {
  const response = await wealthFetch(
    buildStockSearchUrl(keyword, options.limit ?? DEFAULT_STOCK_SEARCH_LIMIT),
    {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: options.signal,
    },
  );
  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    let code = `HTTP_${response.status}`;
    try {
      const payload = (await response.json()) as { code?: string; message?: string };
      if (payload.message) message = payload.message;
      if (payload.code) code = payload.code;
    } catch {
      // Keep the bounded transport fallback when the server did not return JSON.
    }
    throw new StockSearchApiError(message, code);
  }
  return (await response.json()) as StockSearchResponseDto;
}
