import { wealthFetch } from "../../../../../shared/api/wealthApiClient";
import type { SectorRelativeRotationResultsRequest } from "../model/sectorRelativeRotationTypes";

const API_ROOT = "/api/v1/wealth/market/sector-analysis/relative-rotation";

export class SectorRelativeRotationApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code = "SA_QUERY_FAILED", status = 0) {
    super(message);
    this.name = "SectorRelativeRotationApiError";
    this.code = code;
    this.status = status;
  }
}
export function buildSectorRelativeRotationMetaUrl(market: "CN_A" = "CN_A"): string {
  const url = new URL(`${API_ROOT}/meta`, window.location.origin);
  url.searchParams.set("market", market);
  return url.toString();
}

export function buildSectorRelativeRotationResultsUrl(request: SectorRelativeRotationResultsRequest): string {
  const url = new URL(`${API_ROOT}/results`, window.location.origin);
  Object.entries(request).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value));
  });
  return url.toString();
}

export function fetchSectorRelativeRotationMeta(market: "CN_A", options: { signal?: AbortSignal } = {}): Promise<unknown> {
  return fetchJson(buildSectorRelativeRotationMetaUrl(market), options);
}

export function fetchSectorRelativeRotationResults(request: SectorRelativeRotationResultsRequest, options: { signal?: AbortSignal } = {}): Promise<unknown> {
  return fetchJson(buildSectorRelativeRotationResultsUrl(request), options);
}

async function fetchJson(url: string, options: { signal?: AbortSignal }): Promise<unknown> {
  const response = await wealthFetch(url, { method: "GET", headers: { Accept: "application/json" }, signal: options.signal });
  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    let code = `HTTP_${response.status}`;
    try {
      const payload = await response.json() as { code?: string; message?: string };
      if (payload.message) message = payload.message;
      if (payload.code) code = payload.code;
    } catch {
      // Preserve the bounded HTTP fallback for non-JSON responses.
    }
    throw new SectorRelativeRotationApiError(message, code, response.status);
  }
  return response.json();
}
