import { wealthFetch } from "../../../../../shared/api/wealthApiClient";
import type {
  SectorHistoryRange,
  SectorMomentumDirection,
  SectorMomentumPeriod,
  SectorMomentumScope,
} from "../model/sectorMomentumTypes";

const API_ROOT = "/api/v1/wealth/market/sector-analysis";

export class SectorMomentumApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code = "SA_QUERY_FAILED", status = 0) {
    super(message);
    this.name = "SectorMomentumApiError";
    this.code = code;
    this.status = status;
  }
}

export interface SectorMomentumRankingRequest {
  market: "CN_A";
  tradeDate?: string;
  scope: SectorMomentumScope;
  level1Code?: string;
  level2Code?: string;
  period: SectorMomentumPeriod;
  direction: SectorMomentumDirection;
  debug?: 0 | 1;
}

export interface SectorMomentumHistoryRequest extends Omit<SectorMomentumRankingRequest, "direction"> {
  historyRange: SectorHistoryRange;
  sectorCode: string;
}

export function buildSectorMomentumMetaUrl(market: "CN_A" = "CN_A"): string {
  const url = new URL(`${API_ROOT}/meta`, window.location.origin);
  url.searchParams.set("market", market);
  return url.toString();
}

export function buildSectorMomentumRankingsUrl(request: SectorMomentumRankingRequest): string {
  return buildUrl(`${API_ROOT}/momentum/rankings`, request);
}

export function buildSectorMomentumHistoryUrl(request: SectorMomentumHistoryRequest): string {
  return buildUrl(`${API_ROOT}/momentum/history`, request);
}

export function fetchSectorMomentumMeta(
  market: "CN_A",
  options: { signal?: AbortSignal } = {},
): Promise<unknown> {
  return fetchJson(buildSectorMomentumMetaUrl(market), options);
}

export function fetchSectorMomentumRankings(
  request: SectorMomentumRankingRequest,
  options: { signal?: AbortSignal } = {},
): Promise<unknown> {
  return fetchJson(buildSectorMomentumRankingsUrl(request), options);
}

export function fetchSectorMomentumHistory(
  request: SectorMomentumHistoryRequest,
  options: { signal?: AbortSignal } = {},
): Promise<unknown> {
  return fetchJson(buildSectorMomentumHistoryUrl(request), options);
}

function buildUrl(path: string, request: object): string {
  const url = new URL(path, window.location.origin);
  Object.entries(request).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value));
  });
  return url.toString();
}

async function fetchJson(url: string, options: { signal?: AbortSignal }): Promise<unknown> {
  const response = await wealthFetch(url, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal: options.signal,
  });
  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    let code = `HTTP_${response.status}`;
    try {
      const payload = await response.json() as { code?: string; message?: string };
      if (payload.message) message = payload.message;
      if (payload.code) code = payload.code;
    } catch {
      // Keep the bounded status fallback for non-JSON responses.
    }
    throw new SectorMomentumApiError(message, code, response.status);
  }
  return response.json();
}
