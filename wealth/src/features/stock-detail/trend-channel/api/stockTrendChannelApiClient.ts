import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { StockTrendChannelResponseDto } from "./stockTrendChannelApiTypes";

export class StockTrendChannelApiError extends Error {
  code: string;

  constructor(message: string, code: string) {
    super(message);
    this.code = code;
  }
}

export async function fetchStockTrendChannel(
  params: { tsCode: string; endDate: string; limit?: number },
  options: { signal?: AbortSignal } = {},
): Promise<StockTrendChannelResponseDto> {
  const url = new URL("/api/v1/wealth/market/stock-detail/trend-channel", window.location.origin);
  url.searchParams.set("tsCode", params.tsCode);
  url.searchParams.set("endDate", params.endDate);
  url.searchParams.set("limit", String(params.limit ?? 300));
  const response = await wealthFetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  if (response.ok) return (await response.json()) as StockTrendChannelResponseDto;

  let code = `HTTP_${response.status}`;
  let message = `股票趋势通道请求失败：${response.status}`;
  try {
    const payload = (await response.json()) as { code?: string; message?: string };
    if (payload.code) code = payload.code;
    if (payload.message) message = payload.message;
  } catch {
    // Keep the stable status-based fallback for non-JSON failures.
  }
  throw new StockTrendChannelApiError(message, code);
}
