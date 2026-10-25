import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { IndexDetailApiError } from "../api/indexDetailApiClient";

export async function fetchDailyWaveReview(
  { tsCode }: { tsCode: "000001.SH" },
  { signal }: { signal: AbortSignal },
): Promise<unknown> {
  const url = new URL("/api/v1/wealth/market/index-detail/daily-waves", window.location.origin);
  url.searchParams.set("tsCode", tsCode);
  const response = await wealthFetch(url, { method: "GET", cache: "no-store", signal });
  if (!response.ok) {
    let code = `HTTP_${response.status}`;
    let message = "波段划分计算失败，请重试";
    try {
      const payload: unknown = await response.json();
      if (payload !== null && typeof payload === "object") {
        if ("code" in payload && typeof payload.code === "string") code = payload.code;
        if ("message" in payload && typeof payload.message === "string") message = payload.message;
      }
    } catch (error) {
      if (signal.aborted) throw error;
      // Invalid error bodies remain failures, never an empty research result.
    }
    throw new IndexDetailApiError(message, response.status, code);
  }
  return response.json() as Promise<unknown>;
}
