import { wealthFetch } from "../../../shared/api/wealthApiClient";
import type {
  IndexDetailKlineResponseDto,
  IndexDetailPageInitResponseDto,
  IndexDetailWeightsResponseDto,
} from "./indexDetailApiTypes";

interface FetchOptions {
  signal?: AbortSignal;
}

export class IndexDetailApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, status: number, code = `HTTP_${status}`) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export function fetchIndexDetailPageInit(
  params: { tsCode: string; tradeDate?: string; debug?: 0 | 1 },
  options: FetchOptions = {},
): Promise<IndexDetailPageInitResponseDto> {
  return fetchIndexDetail<IndexDetailPageInitResponseDto>("page-init", params, options);
}

export function fetchIndexDetailKline(
  params: { tsCode: string; period: "day"; endDate?: string; limit?: number; debug?: 0 | 1 },
  options: FetchOptions = {},
): Promise<IndexDetailKlineResponseDto> {
  return fetchIndexDetail<IndexDetailKlineResponseDto>("kline", params, options);
}

export function fetchIndexDetailWeights(
  params: { tsCode: string; tradeDate?: string; debug?: 0 | 1 },
  options: FetchOptions = {},
): Promise<IndexDetailWeightsResponseDto> {
  return fetchIndexDetail<IndexDetailWeightsResponseDto>("weights", params, options);
}

async function fetchIndexDetail<T>(
  endpoint: "page-init" | "kline" | "weights",
  params: Record<string, string | number | undefined>,
  options: FetchOptions,
): Promise<T> {
  const url = new URL(`/api/v1/wealth/market/index-detail/${endpoint}`, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value));
  });
  const response = await wealthFetch(url, { method: "GET", signal: options.signal });
  if (!response.ok) throw await readIndexDetailError(response);
  return (await response.json()) as T;
}

async function readIndexDetailError(response: Response): Promise<IndexDetailApiError> {
  let code = `HTTP_${response.status}`;
  let message = `指数详情请求失败：${response.status}`;
  try {
    const payload = (await response.json()) as { code?: string; message?: string };
    if (payload.code) code = payload.code;
    if (payload.message) message = payload.message;
  } catch {
    // Keep the stable status-based fallback when the body is not JSON.
  }
  return new IndexDetailApiError(message, response.status, code);
}
