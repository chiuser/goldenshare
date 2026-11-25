import { wealthFetch } from "../../../shared/api/wealthApiClient";
import type { StockDetailFetchOptions } from "./stockDetailApiClient";
import type {
  StockMinuteChartResponseDto,
  StockMinuteFrequency,
} from "./stockMinuteApiTypes";

export interface StockMinuteFetchParams {
  tsCode: string;
  freq: StockMinuteFrequency;
  startDate?: string;
  endDate?: string;
  limit?: number;
  cursor?: string;
  debug?: 0 | 1;
}

function buildMinuteUrl(params: StockMinuteFetchParams): string {
  const url = new URL(`/api/v1/wealth/market/stock-detail/minutes`, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (typeof value !== "undefined") url.searchParams.set(key, String(value));
  });
  return url.toString();
}

async function parseMinuteResponse<T>(response: Response): Promise<T> {
  if (response.ok) return (await response.json()) as T;

  let message = `请求失败：${response.status}`;
  let code = `HTTP_${response.status}`;
  try {
    const payload = (await response.json()) as { code?: string; message?: string };
    if (payload.message) message = payload.message;
    if (payload.code) code = payload.code;
  } catch {
    // keep the HTTP fallback
  }
  const error = new Error(message) as Error & { code: string };
  error.name = "StockDetailApiError";
  error.code = code;
  throw error;
}

export async function fetchStockMinuteChart(
  params: StockMinuteFetchParams,
  options: StockDetailFetchOptions = {},
): Promise<StockMinuteChartResponseDto> {
  const response = await wealthFetch(buildMinuteUrl(params), {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  return parseMinuteResponse<StockMinuteChartResponseDto>(response);
}
