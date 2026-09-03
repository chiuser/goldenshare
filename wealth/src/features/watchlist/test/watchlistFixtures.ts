import type {
  WatchlistItemDto,
  WatchlistPageResponseDto,
} from "../api/watchlistApiTypes";

export function item(
  id = 1,
  overrides: Partial<WatchlistItemDto> = {},
): WatchlistItemDto {
  return {
    id,
    addedAt: "2026-09-03T01:00:00Z",
    stock: {
      tsCode: `${String(id).padStart(6, "0")}.SZ`,
      name: `股票${id}`,
      industry: "银行",
      listStatus: "L",
    },
    quote: { price: 12.34, changePct: 1.73, vol: 1234567, direction: "UP" },
    valuation: { peTtm: 5.62, pb: 0.71 },
    activity: { volumeRatio: 1.08, turnoverRate: 0.92 },
    moneyFlow: { netAmount: -2189.4, direction: "DOWN" },
    missingFields: [],
    ...overrides,
  };
}
export function page(
  items: WatchlistItemDto[] = [item()],
  overrides: Partial<WatchlistPageResponseDto> = {},
): WatchlistPageResponseDto {
  return {
    pageContext: {
      market: "CN_A",
      tradeDate: "2026-09-02",
      prevTradeDate: "2026-09-01",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: "2026-09-03T01:00:00Z",
      source: "explicit",
    },
    dataStatus: {
      status: items.length ? "READY" : "EMPTY",
      expectedTradeDate: "2026-09-02",
      observedTradeDate: items.length ? "2026-09-02" : null,
    },
    totalCount: items.length,
    nextCursor: null,
    items,
    ...overrides,
  };
}
export function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((ok, fail) => {
    resolve = ok;
    reject = fail;
  });
  return { promise, resolve, reject };
}
