import { wealthFetch } from "../../../shared/api/wealthApiClient";
import type * as D from "./watchlistApiTypes";
const BASE = "/api/v1/wealth/market/watchlist";
export interface WatchlistFetchOptions {
  signal?: AbortSignal;
}
export interface WatchlistPageRequest {
  groupId: number;
  limit?: number;
  cursor?: string;
  tradeDate?: string;
  sortBy?: D.WatchlistSortField;
  direction?: "desc" | "asc";
}
export class WatchlistApiError extends Error {
  constructor(message: string, public code: string, public outcome: "FAILED" | "UNKNOWN" = "FAILED") {
    super(message);
  }
}
type Check = (value: unknown) => boolean;
const record = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);
const str: Check = v => typeof v === "string";
const bool: Check = v => typeof v === "boolean";
const count: Check = v => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const id: Check = v => count(v) && v as number > 0;
const numeric: Check = v => typeof v === "number" && Number.isFinite(v);
const nullable = (check: Check): Check => v => v === null || check(v);
const list = (check: Check): Check => v => Array.isArray(v) && v.every(check);
const values = (...allowed: unknown[]): Check => v => allowed.includes(v);
const shape = (fields: Record<string, Check>): Check => v => record(v) && Object.keys(v).length === Object.keys(fields).length && Object.entries(fields).every(([k, check]) => Object.hasOwn(v, k) && check(v[k]));
const uniqueIds: Check = v => Array.isArray(v) && v.every(id) && new Set(v).size === v.length;
const color: Check = v => typeof v === "string" && /^#[0-9A-F]{6}$/.test(v);
const direction = values("UP", "DOWN", "FLAT", "UNKNOWN");
const group = shape({
  id,
  name: str,
  isDefault: bool,
  color: nullable(color),
  memberCount: count,
  createdAt: str
});
const rules = shape({
  maxGroups: count,
  maxCustomGroups: count,
  nameMaxVisibleChars: count,
  nameMaxUtf8Bytes: count,
  maxBatchMemberships: count,
  palette: list(color)
});
const groups = shape({
  groups: list(group),
  rules
});
const groupMutation = shape({
  group
});
const groupDelete = shape({
  deletedGroupId: id,
  deletedMemberCount: count,
  nextGroupId: id
});
const summary = shape({
  totalCount: count
});
const mark = shape({
  groupId: id,
  name: str,
  color
});
const page = shape({
  group,
  pageContext: shape({
    market: values("CN_A"),
    tradeDate: str,
    prevTradeDate: nullable(str),
    isTradingDay: bool,
    sessionStatus: values("PRE_OPEN", "TRADING", "BREAK", "CLOSED"),
    timezone: values("Asia/Shanghai"),
    generatedAt: str,
    source: values("explicit", "default")
  }),
  dataStatus: shape({
    status: values("READY", "DELAYED", "PARTIAL", "EMPTY", "ERROR"),
    expectedTradeDate: str,
    observedTradeDate: nullable(str)
  }),
  items: list(shape({
    membershipId: id,
    addedAt: str,
    isPinned: bool,
    groupMarks: list(mark),
    stock: shape({
      tsCode: str,
      name: str,
      industry: nullable(str),
      listStatus: nullable(str)
    }),
    quote: shape({
      price: nullable(numeric),
      changePct: nullable(numeric),
      vol: nullable(numeric),
      direction
    }),
    valuation: shape({
      peTtm: nullable(numeric),
      pb: nullable(numeric)
    }),
    activity: shape({
      volumeRatio: nullable(numeric),
      turnoverRate: nullable(numeric)
    }),
    moneyFlow: shape({
      netAmount: nullable(numeric),
      direction
    }),
    missingFields: list(str)
  })),
  totalCount: count,
  nextCursor: nullable(v => typeof v === "string" && v.length > 0)
});
const search = shape({
  groupId: id,
  keyword: str,
  items: list(shape({
    tsCode: str,
    name: str,
    status: values("AVAILABLE", "ADDED")
  }))
});
const added = shape({
  groupId: id,
  tsCode: str,
  isAdded: values(true),
  created: bool,
  memberCount: count
});
const batch = shape({
  action: values("MOVE", "ADD_TO_GROUPS", "REMOVE", "PIN", "UNPIN"),
  requestedCount: count,
  createdCount: count,
  removedCount: count,
  updatedCount: count,
  groupCounts: list(shape({
    groupId: id,
    memberCount: count
  }))
});
const stockGroups = shape({
  tsCode: str,
  isAdded: bool,
  groups: list(shape({
    groupId: id,
    name: str,
    isDefault: bool,
    color: nullable(color),
    selected: bool
  }))
});
const replaced = shape({
  tsCode: str,
  isAdded: values(true),
  groupIds: v => uniqueIds(v) && (v as unknown[]).length > 0,
  createdCount: count,
  removedCount: count
});
function url(path: string, params: Record<string, string | number | undefined> = {}) {
  const target = new URL(BASE + path, window.location.origin);
  for (const [key, value] of Object.entries(params)) if (value !== undefined) target.searchParams.set(key, String(value));
  return target.toString();
}
function groupPath(groupId: number) {
  if (!id(groupId)) throw new WatchlistApiError("分组 ID 无效", "WL_REQUEST_INVALID");
  return `/groups/${groupId}`;
}
const stockCode = (code: string) => code.trim().toUpperCase();
const stockPath = (code: string) => `/stocks/${encodeURIComponent(stockCode(code))}/groups`;
async function request<T>(path: string, method: string, validate: Check, options: WatchlistFetchOptions = {}, body?: unknown, timeout = 5000): Promise<T> {
  const controller = new AbortController();
  let rejectAbort!: (error: DOMException) => void;
  const aborted = new Promise<never>((_, reject) => {
    rejectAbort = reject;
  });
  const cancel = () => {
    controller.abort();
    rejectAbort(new DOMException("Request aborted", "AbortError"));
  };
  options.signal?.addEventListener("abort", cancel, {
    once: true
  });
  if (options.signal?.aborted) cancel();
  const timer = window.setTimeout(cancel, timeout);
  const unknownOutcome = () => new WatchlistApiError("提交结果待确认，请先读取最新状态", "WL_WRITE_OUTCOME_UNKNOWN", "UNKNOWN");
  try {
    return await Promise.race([aborted, (async () => {
      const response = await wealthFetch(path, {
        method,
        signal: controller.signal,
        ...(body === undefined ? {} : {
          headers: {
            "Content-Type": "application/json"
          },
          body: JSON.stringify(body)
        })
      });
      if (!response.ok) {
        const payload: unknown = await response.json().catch(() => null);
        if (!record(payload) || !str(payload.code) || !str(payload.message)) {
          if (method !== "GET") throw unknownOutcome();
          throw new WatchlistApiError(`请求失败：${response.status}`, "WL_QUERY_FAILED");
        }
        const uncertain = payload.code === "WL_WRITE_OUTCOME_UNKNOWN" || method !== "GET" && response.status >= 500 && payload.code !== "WL_WRITE_FAILED";
        throw new WatchlistApiError(payload.message as string, payload.code as string, uncertain ? "UNKNOWN" : "FAILED");
      }
      const payload: unknown = await response.json();
      if (!validate(payload)) {
        if (method !== "GET") throw unknownOutcome();
        throw new WatchlistApiError("自选响应不符合数据合同，请重试读取", "WL_QUERY_FAILED");
      }
      return payload as T;
    })()]);
  } catch (error) {
    if (error instanceof WatchlistApiError) throw error;
    if (method !== "GET") throw unknownOutcome();
    if (options.signal?.aborted) throw error;
    throw new WatchlistApiError(controller.signal.aborted ? "请求超时，请重试读取" : "自选数据暂不可用，请重试读取", "WL_QUERY_FAILED");
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener("abort", cancel);
  }
}
export const fetchWatchlistGroups = (options: WatchlistFetchOptions = {}) => request<D.WatchlistGroupsResponseDto>(url("/groups"), "GET", groups, options);
export const createWatchlistGroup = (body: {
  name: string;
  color: string;
}) => request<D.WatchlistGroupMutationResponseDto>(url("/groups"), "POST", groupMutation, {}, body);
export const changeWatchlistGroupColor = (groupId: number, color: string) => request<D.WatchlistGroupMutationResponseDto>(url(groupPath(groupId) + "/color"), "PATCH", groupMutation, {}, {
  color
});
export const deleteWatchlistGroup = (groupId: number) => request<D.WatchlistGroupDeleteResponseDto>(url(groupPath(groupId)), "DELETE", groupDelete);
export const fetchWatchlistSummary = (options: WatchlistFetchOptions = {}) => request<D.WatchlistSummaryResponseDto>(url("/summary"), "GET", summary, options);
export const fetchWatchlistPage = ({
  groupId,
  ...params
}: WatchlistPageRequest, options: WatchlistFetchOptions = {}) => request<D.WatchlistPageResponseDto>(url(groupPath(groupId) + "/items", params), "GET", v => page(v) && record(v) && record(v.group) && v.group.id === groupId, options);
export const searchWatchlistCandidates = ({
  groupId,
  ...params
}: {
  groupId: number;
  keyword: string;
  limit?: number;
}, options: WatchlistFetchOptions = {}) => request<D.WatchlistSearchResponseDto>(url(groupPath(groupId) + "/search", params), "GET", v => search(v) && record(v) && v.groupId === groupId, options, undefined, 2000);
export const addWatchlistGroupItem = (groupId: number, tsCode: string) => request<D.WatchlistAddResponseDto>(url(groupPath(groupId) + `/items/${encodeURIComponent(stockCode(tsCode))}`), "PUT", v => added(v) && record(v) && v.groupId === groupId && v.tsCode === stockCode(tsCode));
export const fetchStockWatchlistGroups = (tsCode: string, options: WatchlistFetchOptions = {}) => request<D.WatchlistStockGroupsResponseDto>(url(stockPath(tsCode)), "GET", v => stockGroups(v) && record(v) && v.tsCode === stockCode(tsCode), options);
export const replaceStockWatchlistGroups = (tsCode: string, groupIds: number[]) => request<D.WatchlistStockGroupsReplaceResponseDto>(url(stockPath(tsCode)), "PUT", v => replaced(v) && record(v) && v.tsCode === stockCode(tsCode), {}, {
  groupIds
});
export function batchWatchlistItems(groupId: number, action: D.WatchlistBatchAction, membershipIds: number[], targetGroupIds: number[] = []) {
  const paths = {
    MOVE: "move",
    ADD_TO_GROUPS: "add-to-groups",
    REMOVE: "remove",
    PIN: "pin",
    UNPIN: "unpin"
  } as const;
  const body = {
    membershipIds,
    ...(action === "MOVE" ? {
      targetGroupId: targetGroupIds[0]
    } : action === "ADD_TO_GROUPS" ? {
      targetGroupIds
    } : {})
  };
  return request<D.WatchlistBatchActionResponseDto>(url(groupPath(groupId) + `/actions/${paths[action]}`), "POST", v => batch(v) && record(v) && v.action === action, {}, body);
}
