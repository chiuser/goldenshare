import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  addWatchlistItem,
  fetchWatchlistPage,
  removeWatchlistItem,
  WatchlistApiError,
} from "../api/watchlistApi";
import { deferred, item, page } from "../test/watchlistFixtures";
import { useWatchlistController } from "./useWatchlistController";
import type { WatchlistPageResponseDto } from "../api/watchlistApiTypes";

vi.mock("../api/watchlistApi", async (original) => ({
  ...(await original<typeof import("../api/watchlistApi")>()),
  fetchWatchlistPage: vi.fn(),
  addWatchlistItem: vi.fn(),
  removeWatchlistItem: vi.fn(),
}));
const fetchPage = vi.mocked(fetchWatchlistPage),
  add = vi.mocked(addWatchlistItem),
  remove = vi.mocked(removeWatchlistItem);
beforeEach(() => {
  vi.resetAllMocks();
  fetchPage.mockResolvedValue(page());
});
const ready = async (result: {
  current: ReturnType<typeof useWatchlistController>;
}) => waitFor(() => expect(result.current.viewState).toBe("ready"));

describe("watchlist controller", () => {
  it("loads an empty list and recovers from query failure without fabricated rows", async () => {
    fetchPage
      .mockRejectedValueOnce(new Error("查询失败"))
      .mockResolvedValueOnce(page([]));
    const { result } = renderHook(() => useWatchlistController());
    await waitFor(() => expect(result.current.viewState).toBe("error"));
    expect(result.current.items).toEqual([]);
    await act(() => result.current.retry());
    expect(result.current.viewState).toBe("empty");
  });
  it("does not offer retry for an invalid request", async () => {
    fetchPage.mockRejectedValue(
      new WatchlistApiError("日期非法", "WL_REQUEST_INVALID"),
    );
    const { result } = renderHook(() => useWatchlistController("invalid"));
    await waitFor(() => expect(result.current.canRetry).toBe(false));
  });
  it("allows only one in-flight cursor and deduplicates without reordering", async () => {
    const later = deferred<WatchlistPageResponseDto>();
    fetchPage
      .mockResolvedValueOnce(
        page([item(2), item(1)], { totalCount: 3, nextCursor: 2 }),
      )
      .mockReturnValueOnce(later.promise);
    const { result } = renderHook(() => useWatchlistController());
    await ready(result);
    act(() => {
      result.current.loadMore();
      result.current.loadMore();
    });
    expect(fetchPage).toHaveBeenCalledTimes(2);
    expect(fetchPage.mock.calls[1][0]?.afterId).toBe(2);
    await act(async () =>
      later.resolve(page([item(1), item(3)], { totalCount: 3 })),
    );
    expect(result.current.items.map((row) => row.id)).toEqual([2, 1, 3]);
    act(() => result.current.loadMore());
    expect(fetchPage).toHaveBeenCalledTimes(2);
  });
  it.each([
    ["2026-09-02", "2026-09-03"],
    ["2026-09-02", null],
    [null, "2026-09-03"],
  ])(
    "discards a mixed-date batch (%s → %s), reloads everything and resets scroll",
    async (initialObserved, observed) => {
      fetchPage
        .mockResolvedValueOnce(
          page([item(1)], {
            totalCount: 2,
            nextCursor: 1,
            dataStatus: {
              status: "PARTIAL",
              expectedTradeDate: "2026-09-03",
              observedTradeDate: initialObserved,
            },
          }),
        )
        .mockResolvedValueOnce(
          page([item(2)], {
            dataStatus: {
              status: "PARTIAL",
              expectedTradeDate: "2026-09-03",
              observedTradeDate: observed,
            },
          }),
        )
        .mockResolvedValueOnce(page([item(9)]));
      const { result } = renderHook(() => useWatchlistController());
      await ready(result);
      const before = result.current.scrollResetKey;
      act(() => result.current.loadMore());
      await waitFor(() =>
        expect(result.current.items.map((row) => row.id)).toEqual([9]),
      );
      expect(result.current.scrollResetKey).toBe(before + 1);
      expect(fetchPage.mock.calls[2][0]?.afterId).toBeUndefined();
    },
  );
  it("reloads from the top when an add tail-read observes a new date", async () => {
    fetchPage
      .mockResolvedValueOnce(page([item(1)]))
      .mockResolvedValueOnce(
        page([item(2)], {
          totalCount: 2,
          dataStatus: {
            status: "READY",
            expectedTradeDate: "2026-09-03",
            observedTradeDate: "2026-09-03",
          },
        }),
      )
      .mockResolvedValueOnce(
        page([item(1), item(2)], {
          dataStatus: {
            status: "READY",
            expectedTradeDate: "2026-09-03",
            observedTradeDate: "2026-09-03",
          },
        }),
      );
    add.mockResolvedValue({
      tsCode: item(2).stock.tsCode,
      isAdded: true,
      created: true,
      totalCount: 2,
    });
    const { result } = renderHook(() => useWatchlistController());
    await ready(result);
    const before = result.current.scrollResetKey;
    await act(() => result.current.appendAddedItem(item(2).stock.tsCode));
    expect(fetchPage.mock.calls[1][0]?.afterId).toBe(1);
    expect(fetchPage.mock.calls[2][0]?.afterId).toBeUndefined();
    expect(result.current.scrollResetKey).toBe(before + 1);
    expect(result.current.items.map((row) => row.id)).toEqual([1, 2]);
    expect(result.current.dataStatus?.observedTradeDate).toBe("2026-09-03");
  });
  it("restarts a first-page request interrupted by a failed add", async () => {
    const first = deferred<WatchlistPageResponseDto>();
    fetchPage
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(page([]));
    add.mockRejectedValueOnce(new Error("添加失败"));
    const { result } = renderHook(() => useWatchlistController());
    await act(async () => {
      await expect(
        result.current.appendAddedItem(item(2).stock.tsCode),
      ).rejects.toThrow("添加失败");
    });
    expect(fetchPage.mock.calls[0][1]?.signal?.aborted).toBe(true);
    expect(result.current.viewState).toBe("empty");
    expect(result.current.pendingCodes).toEqual([]);
    await act(async () => first.resolve(page([item(1)])));
    expect(result.current.items).toEqual([]);
  });
  it("does not hide a reload failure behind the old dated table", async () => {
    fetchPage
      .mockResolvedValueOnce(page([item(1)], { totalCount: 2, nextCursor: 1 }))
      .mockResolvedValueOnce(
        page([item(2)], {
          dataStatus: {
            status: "READY",
            expectedTradeDate: "2026-09-03",
            observedTradeDate: "2026-09-03",
          },
        }),
      )
      .mockRejectedValueOnce(new Error("重载失败"));
    const { result } = renderHook(() => useWatchlistController());
    await ready(result);
    act(() => result.current.loadMore());
    await waitFor(() => expect(result.current.viewState).toBe("error"));
    expect(result.current.items).toEqual([]);
  });
  it("appends by tail read, keeps the deleted maximum id, and uses server count", async () => {
    fetchPage
      .mockResolvedValueOnce(page([item(1), item(7)]))
      .mockResolvedValueOnce(page([item(8)], { totalCount: 2 }));
    remove.mockResolvedValue({
      tsCode: item(7).stock.tsCode,
      isAdded: false,
      removed: true,
      totalCount: 1,
    });
    add.mockResolvedValue({
      tsCode: item(8).stock.tsCode,
      isAdded: true,
      created: true,
      totalCount: 2,
    });
    const { result } = renderHook(() => useWatchlistController());
    await ready(result);
    act(() => result.current.requestRemove(result.current.items[1]));
    await act(() => result.current.confirmRemove());
    await act(() => result.current.appendAddedItem(item(8).stock.tsCode));
    expect(fetchPage.mock.calls[1][0]?.afterId).toBe(7);
    expect(result.current.items.map((row) => row.id)).toEqual([1, 8]);
    expect(result.current.totalCount).toBe(2);
  });
  it("does not insert a new global tail into an incomplete page or duplicate an existing row", async () => {
    fetchPage.mockResolvedValue(
      page([item(1)], { totalCount: 10, nextCursor: 1 }),
    );
    add.mockResolvedValue({
      tsCode: item(99).stock.tsCode,
      isAdded: true,
      created: true,
      totalCount: 11,
    });
    const { result } = renderHook(() => useWatchlistController());
    await ready(result);
    await act(() => result.current.appendAddedItem(item(99).stock.tsCode));
    expect(result.current.items.map((row) => row.id)).toEqual([1]);
    expect(result.current.totalCount).toBe(11);
    expect(fetchPage).toHaveBeenCalledTimes(1);
    add.mockResolvedValue({
      tsCode: item(1).stock.tsCode,
      isAdded: true,
      created: false,
      totalCount: 11,
    });
    await act(() => result.current.appendAddedItem(item(1).stock.tsCode));
    expect(result.current.items).toHaveLength(1);
  });
  it("retains rows on write failure, locks a stock, and ignores aborted stale list data", async () => {
    const stale = deferred<WatchlistPageResponseDto>();
    fetchPage
      .mockResolvedValueOnce(page([item(1)], { totalCount: 2, nextCursor: 1 }))
      .mockReturnValueOnce(stale.promise);
    remove.mockRejectedValueOnce(new Error("移除失败"));
    const { result } = renderHook(() => useWatchlistController());
    await ready(result);
    act(() => {
      result.current.loadMore();
      result.current.requestRemove(result.current.items[0]);
    });
    await act(() => result.current.confirmRemove());
    expect(fetchPage.mock.calls[1][1]?.signal?.aborted).toBe(true);
    await act(async () => stale.resolve(page([item(5)])));
    expect(result.current.items.map((row) => row.id)).toEqual([1]);
    expect(result.current.removeTarget).not.toBeNull();
    expect(result.current.pendingCodes).toEqual([]);
    const pending = deferred<Awaited<ReturnType<typeof addWatchlistItem>>>();
    add.mockReturnValueOnce(pending.promise);
    let task!: Promise<unknown>;
    await act(async () => {
      task = result.current.appendAddedItem(item(2).stock.tsCode);
    });
    await act(async () => {
      await expect(
        result.current.appendAddedItem(item(2).stock.tsCode),
      ).rejects.toThrow("处理中");
    });
    await act(async () => {
      pending.resolve({
        tsCode: item(2).stock.tsCode,
        isAdded: true,
        created: true,
        totalCount: 3,
      });
      await task;
    });
    expect(add).toHaveBeenCalledTimes(1);
  });
  it("cancels requests at unmount and rejects stale first-page responses after date changes", async () => {
    const first = deferred<WatchlistPageResponseDto>();
    fetchPage
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(page([item(2)]));
    const { result, rerender, unmount } = renderHook(
      ({ date }) => useWatchlistController(date),
      { initialProps: { date: "2026-09-01" } },
    );
    rerender({ date: "2026-09-02" });
    await ready(result);
    await act(async () => first.resolve(page([item(1)])));
    expect(result.current.items[0].id).toBe(2);
    expect(fetchPage.mock.calls[0][1]?.signal?.aborted).toBe(true);
    fetchPage.mockReturnValueOnce(deferred<WatchlistPageResponseDto>().promise);
    rerender({ date: "2026-09-03" });
    unmount();
    expect(fetchPage.mock.calls[2][1]?.signal?.aborted).toBe(true);
  });
});
