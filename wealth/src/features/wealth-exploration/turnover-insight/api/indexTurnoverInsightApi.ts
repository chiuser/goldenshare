import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { DataStatus } from "../../../../shared/model/market";
import type {
  TurnoverInsightAmountResponse,
  TurnoverInsightAverageAmountResponse,
  TurnoverInsightAxisResponse,
  TurnoverInsightRequest,
  TurnoverInsightSeriesPointResponse,
} from "./turnoverInsightApi";

export type IndexTurnoverInsightRequest = TurnoverInsightRequest;

export interface IndexTurnoverInsightPanelResponse {
  tsCode: string;
  indexName: string;
  status: Exclude<DataStatus, "DELAYED">;
  summary: {
    current: TurnoverInsightAmountResponse;
    previous: TurnoverInsightAmountResponse;
    delta: TurnoverInsightAmountResponse;
    avg5d: TurnoverInsightAverageAmountResponse;
    avg20d: TurnoverInsightAverageAmountResponse;
  };
  upperAxis: TurnoverInsightAxisResponse | null;
  deltaAxis: TurnoverInsightAxisResponse | null;
  series: TurnoverInsightSeriesPointResponse[];
  message: string | null;
  exceptionCode: string | null;
}

export interface IndexTurnoverInsightResponse {
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
  indices: IndexTurnoverInsightPanelResponse[];
  message: string | null;
  exceptionCode: string | null;
  debugInfo?: {
    candidateTradeDateCount: number;
    scannedFileCount: number;
    scannedRowCount: number;
    exceptions: Array<{
      module: "indexTurnoverInsight";
      code: string;
      severity: "info" | "warn" | "error";
      message: string;
      details?: Record<string, string | number | null> | null;
    }>;
  } | null;
}

export class IndexTurnoverInsightApiError extends Error {
  code: string;
  status: number | null;

  constructor(message: string, code = "INDEX_TURNOVER_INSIGHT_API_ERROR", status: number | null = null) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

export function buildIndexTurnoverInsightUrl(params: IndexTurnoverInsightRequest): string {
  const url = new URL("/api/v1/wealth/market/turnover-insight/indices", window.location.origin);
  url.searchParams.set("market", params.market);
  url.searchParams.set("tradeDate", params.tradeDate);
  if (typeof params.debug !== "undefined") url.searchParams.set("debug", String(params.debug));
  return url.toString();
}

export async function fetchIndexTurnoverInsight(
  params: IndexTurnoverInsightRequest,
  options: { signal?: AbortSignal } = {},
): Promise<IndexTurnoverInsightResponse> {
  const response = await wealthFetch(buildIndexTurnoverInsightUrl(params), {
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
      // Preserve the HTTP status when the bounded error body is not JSON.
    }
    throw new IndexTurnoverInsightApiError(message, code, response.status);
  }
  return (await response.json()) as IndexTurnoverInsightResponse;
}
