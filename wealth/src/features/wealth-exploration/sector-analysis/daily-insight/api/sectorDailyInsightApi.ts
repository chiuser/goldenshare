import { wealthFetch } from "../../../../../shared/api/wealthApiClient";
import type { DailyInsightSnapshotRequest } from "./sectorDailyInsightTypes";

const ROOT = "/api/v1/wealth/market/sector-analysis/daily-insight";
export class DailyInsightApiError extends Error {
  constructor(readonly status: number) { super("每日洞察读取失败。"); }
}
export function fetchSectorDailyInsightMeta(signal: AbortSignal): Promise<unknown> {
  return read(`${ROOT}/meta?market=CN_A`, signal);
}
export function fetchSectorDailyInsightSnapshot(request: DailyInsightSnapshotRequest, signal: AbortSignal): Promise<unknown> {
  const query = new URLSearchParams({ market: "CN_A", tradeDate: request.tradeDate, industryLevel: String(request.industryLevel), batchKey: request.batchKey, hierarchyVersion: request.hierarchyVersion });
  return read(`${ROOT}/snapshot?${query}`, signal);
}
async function read(url: string, signal: AbortSignal): Promise<unknown> {
  const response = await wealthFetch(url, { signal, headers: { Accept: "application/json" } });
  // Never display an HTTP body as user-facing error text.
  if (!response.ok) throw new DailyInsightApiError(response.status);
  return response.json();
}
