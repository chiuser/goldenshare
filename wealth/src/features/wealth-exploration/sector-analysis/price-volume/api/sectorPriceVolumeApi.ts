import { wealthFetch } from "../../../../../shared/api/wealthApiClient";
import type { PriceVolumeDetailsRequest, PriceVolumeSnapshotRequest } from "./sectorPriceVolumeTypes";

const API_ROOT = "/api/v1/wealth/market/sector-analysis/price-volume";

export class SectorPriceVolumeApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code = "SA_QUERY_FAILED", status = 0) {
    super(message);
    this.name = "SectorPriceVolumeApiError";
    this.code = code;
    this.status = status;
  }
}

export function fetchSectorPriceVolumeMeta(options: { signal?: AbortSignal } = {}): Promise<unknown> {
  const url = new URL(`${API_ROOT}/meta`, window.location.origin);
  url.searchParams.set("market", "CN_A");
  return fetchJson(url.toString(), options);
}

export function fetchSectorPriceVolumeSnapshot(request: PriceVolumeSnapshotRequest, options: { signal?: AbortSignal } = {}): Promise<unknown> {
  return fetchJson(buildUrl(`${API_ROOT}/snapshot`, request), options);
}

export function fetchSectorPriceVolumeDetails(request: PriceVolumeDetailsRequest, options: { signal?: AbortSignal } = {}): Promise<unknown> {
  return fetchJson(buildUrl(`${API_ROOT}/details`, request), options);
}

function buildUrl(path: string, request: object): string {
  const url = new URL(path, window.location.origin);
  Object.entries(request).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value));
  });
  return url.toString();
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
      // Keep the bounded fallback for non-JSON errors.
    }
    throw new SectorPriceVolumeApiError(message, code, response.status);
  }
  return response.json();
}
