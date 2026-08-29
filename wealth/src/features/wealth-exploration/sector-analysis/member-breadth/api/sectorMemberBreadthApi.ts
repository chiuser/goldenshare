import { wealthFetch } from "../../../../../shared/api/wealthApiClient";
import type { SectorMemberBreadthDetailsRequest, SectorMemberBreadthRankingsRequest } from "../model/sectorMemberBreadthTypes";

const API_ROOT = "/api/v1/wealth/market/sector-analysis/member-breadth";

export class SectorMemberBreadthApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, code = "SA_BREADTH_QUERY_FAILED", status = 0) {
    super(message); this.name = "SectorMemberBreadthApiError"; this.code = code; this.status = status;
  }
}

export function fetchSectorMemberBreadthMeta(market: "CN_A", options: { signal?: AbortSignal } = {}): Promise<unknown> {
  return fetchJson(buildUrl("meta", { market }), options);
}
export function fetchSectorMemberBreadthRankings(request: SectorMemberBreadthRankingsRequest, options: { signal?: AbortSignal } = {}): Promise<unknown> {
  return fetchJson(buildUrl("rankings", request), options);
}
export function fetchSectorMemberBreadthDetails(request: SectorMemberBreadthDetailsRequest, options: { signal?: AbortSignal } = {}): Promise<unknown> {
  return fetchJson(buildUrl("details", request), options);
}

function buildUrl(path: string, request: object): string {
  const url = new URL(`${API_ROOT}/${path}`, window.location.origin);
  for (const [key, value] of Object.entries(request)) if (value !== undefined) url.searchParams.set(key, String(value));
  return url.toString();
}

async function fetchJson(url: string, options: { signal?: AbortSignal }): Promise<unknown> {
  const response = await wealthFetch(url, { method: "GET", headers: { Accept: "application/json" }, signal: options.signal });
  if (!response.ok) {
    let message = `请求失败：${response.status}`; let code = `HTTP_${response.status}`;
    try { const payload = await response.json() as { code?: string; message?: string }; if (payload.message) message = payload.message; if (payload.code) code = payload.code; } catch { /* bounded fallback */ }
    throw new SectorMemberBreadthApiError(message, code, response.status);
  }
  return response.json();
}
