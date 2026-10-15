import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { indexDetailRequests } from "../api/indexDetailRequestScheduler";
import type { XxmPeriod, XxmResponse } from "./types";

export const XXM_TIMEOUT_MS = 5000;

export function fetchXxm(params: { tsCode: string; period: XxmPeriod; startDate: string; endDate: string; limit: number },
  signal: AbortSignal): Promise<XxmResponse> {
  return indexDetailRequests.run("xxm", () => sendXxm(params, signal), signal);
}

async function sendXxm(params: { tsCode: string; period: XxmPeriod; startDate: string; endDate: string; limit: number },
  signal: AbortSignal): Promise<XxmResponse> {
  const minute = params.period !== "day";
  const endpoint = minute ? "minute-xxm-signals" : "xxm-signals";
  const url = new URL(`/api/v1/wealth/market/index-detail/${endpoint}`, window.location.origin);
  url.search = new URLSearchParams({ tsCode: params.tsCode, startDate: params.startDate, endDate: params.endDate,
    limit: String(params.limit), ...(minute ? { freq: params.period.slice(1) } : { period: "day" }) }).toString();
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort(signal.reason);
  signal.addEventListener("abort", abort, { once: true });
  if (signal.aborted) abort();
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, XXM_TIMEOUT_MS);
  try {
    const response = await wealthFetch(url, { signal: controller.signal });
    if (!response.ok) {
      const payload = await response.json().catch(() => null) as { message?: string } | null;
      throw new Error(payload?.message || "研究指标加载失败，请重试");
    }
    return await response.json() as XxmResponse;
  } catch (error) {
    if (timedOut) throw new Error("研究指标加载超时，请重试");
    if (error instanceof TypeError) throw new Error("研究指标暂时无法连接，请重试");
    throw error;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener("abort", abort);
  }
}
