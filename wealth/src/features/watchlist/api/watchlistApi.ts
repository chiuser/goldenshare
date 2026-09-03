import { wealthFetch } from "../../../shared/api/wealthApiClient";
import type {
  WatchlistAddResponseDto,
  WatchlistMembershipResponseDto,
  WatchlistPageResponseDto,
  WatchlistRemoveResponseDto,
  WatchlistSearchResponseDto,
  WatchlistSummaryResponseDto,
} from "./watchlistApiTypes";

const BASE = "/api/v1/wealth/market/watchlist";
const REQUEST_TIMEOUT_MS = 5000;
const SEARCH_TIMEOUT_MS = 2000;
export interface WatchlistFetchOptions {
  signal?: AbortSignal;
}
export interface WatchlistPageRequest {
  limit?: number;
  afterId?: number;
  tradeDate?: string;
}
export class WatchlistApiError extends Error {
  constructor(
    message: string,
    public code: string,
  ) {
    super(message);
  }
}

async function request<T>(
  path: string,
  method: string,
  options: WatchlistFetchOptions,
  validate: (value: unknown) => boolean,
  timeout = REQUEST_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  options.signal?.addEventListener("abort", cancel, { once: true });
  if (options.signal?.aborted) controller.abort();
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeout);
  try {
    const response = await wealthFetch(path, {
      method,
      signal: controller.signal,
    });
    if (!response.ok) {
      const payload: unknown = await response.json().catch(() => null);
      throw new WatchlistApiError(
        isRecord(payload) && typeof payload.message === "string"
          ? payload.message
          : `请求失败：${response.status}`,
        isRecord(payload) && typeof payload.code === "string"
          ? payload.code
          : `HTTP_${response.status}`,
      );
    }
    const payload: unknown = await response.json();
    if (!validate(payload))
      throw new WatchlistApiError(
        "自选响应不符合数据合同，请重试",
        method === "GET" ? "WL_QUERY_FAILED" : "WL_WRITE_FAILED",
      );
    return payload as T;
  } catch (error) {
    if (timedOut)
      throw new WatchlistApiError(
        "请求超时，请重试",
        method === "GET" ? "WL_QUERY_FAILED" : "WL_WRITE_FAILED",
      );
    throw error;
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener("abort", cancel);
  }
}

function url(
  path = "",
  params: Record<string, string | number | undefined> = {},
) {
  const target = new URL(BASE + path, window.location.origin);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) target.searchParams.set(key, String(value));
  });
  return target.toString();
}
function itemUrl(tsCode: string) {
  return url(`/items/${encodeURIComponent(tsCode.trim().toUpperCase())}`);
}
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function isCount(value: unknown) {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}
function isSummary(value: unknown) {
  return isRecord(value) && isCount(value.totalCount);
}
function isMembership(value: unknown) {
  return (
    isRecord(value) &&
    typeof value.tsCode === "string" &&
    typeof value.isAdded === "boolean"
  );
}
function isNumbers(value: unknown, keys: string[]) {
  return (
    isRecord(value) &&
    keys.every(
      (key) =>
        value[key] === null ||
        (typeof value[key] === "number" && Number.isFinite(value[key])),
    )
  );
}
function isDirection(value: unknown) {
  return ["UP", "DOWN", "FLAT", "UNKNOWN"].includes(value as string);
}
function isPage(value: unknown) {
  if (
    !isRecord(value) ||
    !isSummary(value) ||
    !isRecord(value.pageContext) ||
    !isRecord(value.dataStatus) ||
    !Array.isArray(value.items)
  )
    return false;
  return (
    typeof value.pageContext.tradeDate === "string" &&
    ["PRE_OPEN", "TRADING", "BREAK", "CLOSED"].includes(
      value.pageContext.sessionStatus as string,
    ) &&
    typeof value.dataStatus.expectedTradeDate === "string" &&
    (value.dataStatus.observedTradeDate === null ||
      typeof value.dataStatus.observedTradeDate === "string") &&
    ["READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"].includes(
      value.dataStatus.status as string,
    ) &&
    (value.nextCursor === null ||
      (isCount(value.nextCursor) && (value.nextCursor as number) > 0)) &&
    value.items.every(
      (item) =>
        isRecord(item) &&
        isCount(item.id) &&
        typeof item.addedAt === "string" &&
        isRecord(item.stock) &&
        typeof item.stock.tsCode === "string" &&
        typeof item.stock.name === "string" &&
        (item.stock.industry === null ||
          typeof item.stock.industry === "string") &&
        isNumbers(item.quote, ["price", "changePct", "vol"]) &&
        isRecord(item.quote) &&
        isDirection(item.quote.direction) &&
        isNumbers(item.valuation, ["peTtm", "pb"]) &&
        isNumbers(item.activity, ["volumeRatio", "turnoverRate"]) &&
        isNumbers(item.moneyFlow, ["netAmount"]) &&
        isRecord(item.moneyFlow) &&
        isDirection(item.moneyFlow.direction) &&
        Array.isArray(item.missingFields) &&
        item.missingFields.every((field) => typeof field === "string"),
    )
  );
}

export const fetchWatchlistPage = (
  params: WatchlistPageRequest = {},
  options: WatchlistFetchOptions = {},
) =>
  request<WatchlistPageResponseDto>(
    url("", { ...params }),
    "GET",
    options,
    isPage,
  );
export const fetchWatchlistSummary = (options: WatchlistFetchOptions = {}) =>
  request<WatchlistSummaryResponseDto>(
    url("/summary"),
    "GET",
    options,
    isSummary,
  );
export const searchWatchlistCandidates = (
  params: { keyword: string; limit?: number },
  options: WatchlistFetchOptions = {},
) =>
  request<WatchlistSearchResponseDto>(
    url("/search", params),
    "GET",
    options,
    (value) =>
      isRecord(value) &&
      typeof value.keyword === "string" &&
      Array.isArray(value.items) &&
      value.items.every(
        (item) =>
          isRecord(item) &&
          typeof item.tsCode === "string" &&
          typeof item.name === "string" &&
          ["AVAILABLE", "ADDED"].includes(item.status as string),
      ),
    SEARCH_TIMEOUT_MS,
  );
export const fetchWatchlistMembership = (
  tsCode: string,
  options: WatchlistFetchOptions = {},
) =>
  request<WatchlistMembershipResponseDto>(
    itemUrl(tsCode),
    "GET",
    options,
    isMembership,
  );
export const addWatchlistItem = (
  tsCode: string,
  options: WatchlistFetchOptions = {},
) =>
  request<WatchlistAddResponseDto>(
    itemUrl(tsCode),
    "PUT",
    options,
    (value) =>
      isMembership(value) &&
      isSummary(value) &&
      isRecord(value) &&
      typeof value.created === "boolean",
  );
export const removeWatchlistItem = (
  tsCode: string,
  options: WatchlistFetchOptions = {},
) =>
  request<WatchlistRemoveResponseDto>(
    itemUrl(tsCode),
    "DELETE",
    options,
    (value) =>
      isMembership(value) &&
      isSummary(value) &&
      isRecord(value) &&
      typeof value.removed === "boolean",
  );
