import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { IndexDetailApiError } from "./indexDetailApiClient";

export interface TrendChannelRawResponse {
  instrument: { ts_code: "000001.SH"; name: string; security_type: "index" };
  period: "day";
  adjustment: "none";
  formula: {
    key: "high-low-ema-hysteresis";
    version: "sse-daily-trend-channel-v1";
    short_period: 25;
    long_period: 90;
    seed: "first_observation";
    state_rule: "strict_close_breakout_inside_retention";
  };
  data_status: {
    status: "READY" | "EMPTY";
    observed_trade_date: string | null;
    as_of_time: string;
    is_provisional: false;
    note: string | null;
  };
  bars: TrendChannelRawBar[];
  meta: {
    bar_count: number;
    limit: number;
    start_date: string | null;
    end_date: string | null;
    has_more_history: boolean;
    next_end_date: string | null;
  };
}

export interface TrendChannelRawBar {
  trade_date: string;
  open: string;
  high: string;
  low: string;
  close: string;
  short_channel: TrendChannelRawBand;
  long_channel: TrendChannelRawBand;
  combined_state: "UNKNOWN" | "UP_UP" | "UP_DOWN" | "DOWN_UP" | "DOWN_DOWN";
  is_provisional: false;
}

interface TrendChannelRawBand {
  upper: string;
  lower: string;
  position: "ABOVE" | "INSIDE" | "BELOW";
  state: "UNKNOWN" | "UP" | "DOWN";
}

export async function fetchTrendChannel(
  params: { endDate: string; limit?: number },
  options: { signal?: AbortSignal } = {},
): Promise<TrendChannelRawResponse> {
  const url = new URL("/api/v1/quote/detail/trend-channel", window.location.origin);
  url.searchParams.set("ts_code", "000001.SH");
  url.searchParams.set("period", "day");
  url.searchParams.set("end_date", params.endDate);
  url.searchParams.set("limit", String(params.limit ?? 300));
  const response = await wealthFetch(url, { method: "GET", signal: options.signal });
  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = `趋势通道请求失败：${response.status}`;
    try {
      const payload = (await response.json()) as { code?: string; message?: string };
      if (payload.code) code = payload.code;
      if (payload.message) message = payload.message;
    } catch {
      // Keep the stable status-based fallback when the body is not JSON.
    }
    throw new IndexDetailApiError(message, response.status, code);
  }
  return (await response.json()) as TrendChannelRawResponse;
}
