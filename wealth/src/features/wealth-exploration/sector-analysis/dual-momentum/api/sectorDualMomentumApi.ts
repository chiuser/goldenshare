import { wealthFetch } from "../../../../../shared/api/wealthApiClient";
import type { SectorDualMomentumResultsRequest } from "../model/sectorDualMomentumTypes";

const API_ROOT = "/api/v1/wealth/market/sector-analysis/dual-momentum";

export class SectorDualMomentumApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code = "SA_QUERY_FAILED", status = 0) {
    super(message);
    this.name = "SectorDualMomentumApiError";
    this.code = code;
    this.status = status;
  }
}

export function buildSectorDualMomentumMetaUrl(market: "CN_A" = "CN_A"): string {
  const url = new URL(`${API_ROOT}/meta`, window.location.origin);
  url.searchParams.set("market", market);
  return url.toString();
}

export function buildSectorDualMomentumResultsUrl(request: SectorDualMomentumResultsRequest): string {
  const url = new URL(`${API_ROOT}/results`, window.location.origin);
  Object.entries(request).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value));
  });
  return url.toString();
}

export function fetchSectorDualMomentumMeta(
  market: "CN_A",
  options: { signal?: AbortSignal } = {},
): Promise<unknown> {
  return fetchJson(buildSectorDualMomentumMetaUrl(market), options);
}

export function fetchSectorDualMomentumResults(
  request: SectorDualMomentumResultsRequest,
  options: { signal?: AbortSignal } = {},
): Promise<unknown> {
  return fetchJson(buildSectorDualMomentumResultsUrl(request), options);
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
      // Keep the bounded HTTP fallback for a non-JSON response.
    }
    throw new SectorDualMomentumApiError(message, code, response.status);
  }
  return response.json();
}
