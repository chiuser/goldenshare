import { wealthFetch } from "../../../shared/api/wealthApiClient";
import type { StockDetailKlineResponseDto, StockDetailPageInitResponseDto } from "./stockDetailApiTypes";

export interface StockDetailFetchOptions {
  signal?: AbortSignal;
}

export class StockDetailApiError extends Error {
  code: string;

  constructor(message: string, code = "STOCK_DETAIL_API_ERROR") {
    super(message);
    this.code = code;
  }
}

function buildUrl(path: string, params: Record<string, string | number | undefined>): string {
  const url = new URL(`/api/v1/wealth/market/stock-detail/${path}`, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (typeof value !== "undefined") url.searchParams.set(key, String(value));
  });
  return url.toString();
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;

  let message = `请求失败：${response.status}`;
  let code = `HTTP_${response.status}`;
  try {
    const payload = (await response.json()) as { code?: string; message?: string };
    if (payload.message) message = payload.message;
    if (payload.code) code = payload.code;
  } catch {
    // keep fallback error
  }
  throw new StockDetailApiError(message, code);
}

export async function fetchStockDetailPageInit(
  params: { tsCode: string; tradeDate?: string; debug?: 0 | 1 },
  options: StockDetailFetchOptions = {},
): Promise<StockDetailPageInitResponseDto> {
  const response = await wealthFetch(buildUrl("page-init", params), {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  return parseResponse<StockDetailPageInitResponseDto>(response);
}

export async function fetchStockDetailKline(
  params: {
    tsCode: string;
    period?: "day";
    adjustment?: "forward";
    tradeDate?: string;
    startDate?: string;
    endDate?: string;
    limit?: number;
    debug?: 0 | 1;
  },
  options: StockDetailFetchOptions = {},
): Promise<StockDetailKlineResponseDto> {
  const response = await wealthFetch(buildUrl("kline", params), {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  return parseResponse<StockDetailKlineResponseDto>(response);
}
