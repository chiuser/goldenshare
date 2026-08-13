import { wealthFetch } from "../../../shared/api/wealthApiClient";
import type { NineTurnPeriod, NineTurnSeriesDto } from "./nineTurnApiTypes";

export interface StockNineTurnFetchParams {
  cursor?: string;
  debug?: 0 | 1;
  endDate?: string;
  limit?: number;
  period: Extract<NineTurnPeriod, "day" | "30" | "60" | "90" | "120">;
  startDate?: string;
  tsCode: string;
}

export interface NineTurnFetchOptions {
  signal?: AbortSignal;
}

export class NineTurnApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.name = "NineTurnApiError";
    this.code = code;
    this.status = status;
  }
}

export async function fetchStockNineTurnSeries(
  params: StockNineTurnFetchParams,
  options: NineTurnFetchOptions = {},
): Promise<NineTurnSeriesDto> {
  const path = params.period === "day" ? "nine-turn" : "minute-nine-turn";
  const url = new URL(`/api/v1/wealth/market/stock-detail/${path}`, window.location.origin);
  url.searchParams.set("tsCode", params.tsCode);
  if (params.period !== "day") url.searchParams.set("freq", params.period);
  if (params.startDate) url.searchParams.set("startDate", params.startDate);
  if (params.endDate) url.searchParams.set("endDate", params.endDate);
  if (typeof params.limit === "number") url.searchParams.set("limit", String(params.limit));
  if (params.cursor) url.searchParams.set("cursor", params.cursor);
  if (typeof params.debug === "number") url.searchParams.set("debug", String(params.debug));
  const response = await wealthFetch(url.toString(), {
    headers: { Accept: "application/json" },
    method: "GET",
    signal: options.signal,
  });
  if (response.ok) return (await response.json()) as NineTurnSeriesDto;

  let message = `九转请求失败：${response.status}`;
  let code = `HTTP_${response.status}`;
  try {
    const payload = (await response.json()) as { code?: string; message?: string };
    if (payload.message) message = payload.message;
    if (payload.code) code = payload.code;
  } catch {
    // Keep the stable HTTP fallback when the error body is not JSON.
  }
  throw new NineTurnApiError(message, code, response.status);
}
