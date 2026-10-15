import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { indexDetailRequests } from "../api/indexDetailRequestScheduler";
import { XXM_TIMEOUT_MS } from "../xxm/apiClient";
import { adaptForecast } from "./adapter";
import type { ForecastPeriod, ForecastResponse } from "./types";

export function fetchForecast(period: ForecastPeriod, asOf: string | undefined, signal: AbortSignal): Promise<ForecastResponse> {
  return indexDetailRequests.run("forecast", () => sendForecast(period, asOf, signal), signal);
}

async function sendForecast(period: ForecastPeriod, asOf: string | undefined, signal: AbortSignal): Promise<ForecastResponse> {
  const params = new URLSearchParams({ tsCode: "000001.SH", period });
  if (asOf) params.set("asOf", asOf);
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, XXM_TIMEOUT_MS);
  try {
    const result = await wealthFetch(`/api/v1/wealth/market/index-detail/xxm-key-point-forecast?${params}`, { signal: controller.signal });
    if (!result.ok) {
      const value = await result.json().catch(() => null) as { message?: string } | null;
      throw new Error(value?.message ?? "关键点预判加载失败，请重试");
    }
    return adaptForecast(await result.json() as ForecastResponse, period, asOf);
  } catch (error) {
    if (timedOut) throw new Error("关键点预判加载超时，请重试");
    throw error;
  } finally {
    window.clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}
