import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus } from "../../../../shared/model/market";

export type TurnoverInsightDirection = "up" | "down" | "flat" | "neutral";

export interface TurnoverInsightRequest {
  market: "CN_A";
  tradeDate: string;
  debug?: 0 | 1;
}

export interface TurnoverInsightAmountResponse {
  amountYi: number | null;
  displayText: string;
  direction: TurnoverInsightDirection;
}

export interface TurnoverInsightAxisResponse {
  minYi: number;
  maxYi: number;
  zeroYi: number | null;
  ticks: Array<{ valueYi: number; displayText: string }>;
}

export interface TurnoverInsightSeriesPointResponse {
  time: string;
  showAxisLabel: boolean;
  currentAmountYi: number | null;
  currentDisplayText: string;
  previousAmountYi: number | null;
  previousDisplayText: string;
  deltaAmountYi: number | null;
  deltaDisplayText: string;
  deltaDirection: "up" | "down" | "flat";
}

export interface TurnoverInsightResponse {
  status: DataStatus;
  tradingDay: {
    market: "CN_A";
    expectedTradeDate: string;
    observedTradeDate: string | null;
    previousObservedTradeDate: string | null;
    isTradingDay: boolean;
    sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
    timezone: "Asia/Shanghai";
    generatedAt: string;
  };
  asOf: string | null;
  unit: "yi";
  unitLabel: "亿";
  summary: {
    current: TurnoverInsightAmountResponse;
    previous: TurnoverInsightAmountResponse;
    delta: TurnoverInsightAmountResponse;
  };
  upperAxis: TurnoverInsightAxisResponse | null;
  deltaAxis: TurnoverInsightAxisResponse | null;
  series: TurnoverInsightSeriesPointResponse[];
  message: string | null;
  exceptionCode: string | null;
  debugInfo?: {
    candidateCount: number;
    exceptions: Array<{
      module: "turnoverInsight";
      code: string;
      severity: "info" | "warn" | "error";
      message: string;
      details?: Record<string, string | number | null> | null;
    }>;
  } | null;
}

export class TurnoverInsightApiError extends Error {
  code: string;

  constructor(message: string, code = "TURNOVER_INSIGHT_API_ERROR") {
    super(message);
    this.code = code;
  }
}

export function buildTurnoverInsightUrl(params: TurnoverInsightRequest): string {
  const url = new URL("/api/v1/wealth/market/turnover-insight", window.location.origin);
  url.searchParams.set("market", params.market);
  url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchTurnoverInsight(
  params: TurnoverInsightRequest,
  options: { signal?: AbortSignal } = {},
): Promise<TurnoverInsightResponse> {
  const response = await wealthFetch(buildTurnoverInsightUrl(params), {
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
      // Keep the bounded HTTP fallback when the error body is not JSON.
    }
    throw new TurnoverInsightApiError(message, code);
  }
  return (await response.json()) as TurnoverInsightResponse;
}
