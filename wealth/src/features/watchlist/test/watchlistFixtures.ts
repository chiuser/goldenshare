import type { WatchlistItemDto, WatchlistPageResponseDto, WatchlistGroupDto, WatchlistGroupRulesDto } from "../api/watchlistApiTypes";
export function item(id = 1, overrides: Partial<WatchlistItemDto> = {}): WatchlistItemDto {
  return {
    membershipId: id,
    isPinned: false,
    groupMarks: [],
    addedAt: "2026-09-03T01:00:00Z",
    stock: {
      tsCode: `${String(id).padStart(6, "0")}.SZ`,
      name: `股票${id}`,
      industry: "银行",
      listStatus: "L"
    },
    quote: {
      price: 12.34,
      changePct: 1.73,
      vol: 1234567,
      direction: "UP"
    },
    valuation: {
      peTtm: 5.62,
      pb: 0.71
    },
    activity: {
      volumeRatio: 1.08,
      turnoverRate: 0.92
    },
    moneyFlow: {
      netAmount: -2189.4,
      direction: "DOWN"
    },
    missingFields: [],
    ...overrides
  };
}
export function page(items: WatchlistItemDto[] = [item()], overrides: Partial<WatchlistPageResponseDto> = {}): WatchlistPageResponseDto {
  return {
    group: group(1, {
      memberCount: items.length
    }),
    pageContext: {
      market: "CN_A",
      tradeDate: "2026-09-02",
      prevTradeDate: "2026-09-01",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: "2026-09-03T01:00:00Z",
      source: "explicit"
    },
    dataStatus: {
      status: items.length ? "READY" : "EMPTY",
      expectedTradeDate: "2026-09-02",
      observedTradeDate: items.length ? "2026-09-02" : null
    },
    totalCount: items.length,
    nextCursor: null,
    items,
    ...overrides
  };
}
export function group(id = 1, overrides: Partial<WatchlistGroupDto> = {}): WatchlistGroupDto {
  return {
    id,
    name: id === 1 ? "我的自选" : `分组${id}`,
    isDefault: id === 1,
    color: id === 1 ? null : "#F7C76B",
    memberCount: 0,
    createdAt: "2026-09-08T00:00:00Z",
    ...overrides
  };
}
export const rules: WatchlistGroupRulesDto = {
  maxGroups: 10,
  maxCustomGroups: 9,
  nameMaxVisibleChars: 6,
  nameMaxUtf8Bytes: 1024,
  maxBatchMemberships: 200,
  palette: ["#F7C76B", "#5AA7FF", "#A78BFA", "#2DD4BF", "#FB923C", "#F472B6", "#A3E635", "#22D3EE"]
};
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((ok, fail) => {
    resolve = ok;
    reject = fail;
  });
  return {
    promise,
    resolve,
    reject
  };
}
