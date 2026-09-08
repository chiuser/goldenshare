import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/watchlistApi";
import { deferred, group, item, page } from "../test/watchlistFixtures";
import { useWatchlistItemsController } from "./useWatchlistItemsController";
vi.mock("../api/watchlistApi", async original => ({
  ...(await original<typeof import("../api/watchlistApi")>()),
  fetchWatchlistPage: vi.fn(),
  addWatchlistGroupItem: vi.fn()
}));
const read = vi.mocked(api.fetchWatchlistPage);
beforeEach(() => {
  vi.resetAllMocks();
  read.mockImplementation(async request => page([item()], {
    group: group(request.groupId)
  }));
});
describe("items controller", () => {
  it("loads one opaque cursor at a time and deduplicates membership IDs without sorting locally", async () => {
    read.mockResolvedValueOnce(page([item(5), item(1)], {
      nextCursor: "opaque",
      totalCount: 3
    }));
    const {
      result,
      unmount
    } = renderHook(() => useWatchlistItemsController(1));
    await waitFor(() => expect(result.current.nextCursor).toBe("opaque"));
    const more = deferred<ReturnType<typeof page>>();
    read.mockReturnValueOnce(more.promise);
    let pending!: Promise<void>;
    act(() => {
      pending = result.current.loadMore();
    });
    await act(() => result.current.loadMore());
    expect(read).toHaveBeenCalledTimes(2);
    await act(async () => {
      more.resolve(page([item(1), item(3)], {
        totalCount: 3
      }));
      await pending;
    });
    expect(result.current.items.map(row => row.membershipId)).toEqual([5, 1, 3]);
    expect(read.mock.calls[1][0].cursor).toBe("opaque");
    expect(result.current.nextCursor).toBeNull();
    unmount();
  });
  it.each(["price", "changePct", "vol", "peTtm", "pb", "volumeRatio", "turnoverRate", "netAmount"] as const)("sorts %s descending first, then ascending, resets when switching tabs", async sortBy => {
    const {
      result,
      rerender
    } = renderHook(({
      id
    }) => useWatchlistItemsController(id), {
      initialProps: {
        id: 1
      }
    });
    await waitFor(() => expect(result.current.viewState).toBe("ready"));
    act(() => result.current.setSort(sortBy));
    await waitFor(() => expect(read.mock.lastCall?.[0]).toMatchObject({
      groupId: 1,
      sortBy,
      direction: "desc"
    }));
    act(() => result.current.setSort(sortBy));
    await waitFor(() => expect(read.mock.lastCall?.[0].direction).toBe("asc"));
    rerender({
      id: 2
    });
    await waitFor(() => expect(read.mock.lastCall?.[0].groupId).toBe(2));
    expect(result.current.sort).toBeNull();
    expect(read.mock.lastCall?.[0].sortBy).toBeUndefined();
    rerender({
      id: 1
    });
    await waitFor(() => expect(read.mock.lastCall?.[0].groupId).toBe(1));
    expect(result.current.sort).toBeNull();
  });
  it.each(["cursor", "date"] as const)("reloads first page once after %s invalidation", async cause => {
    read.mockResolvedValueOnce(page([item()], {
      nextCursor: "old"
    }));
    const {
      result
    } = renderHook(() => useWatchlistItemsController(1));
    await waitFor(() => expect(result.current.nextCursor).toBe("old"));
    if (cause === "cursor") read.mockRejectedValueOnce(new api.WatchlistApiError("游标无效", "WL_CURSOR_INVALID"));else read.mockResolvedValueOnce(page([item(2)], {
      dataStatus: {
        status: "READY",
        expectedTradeDate: "2026-09-03",
        observedTradeDate: "2026-09-03"
      }
    }));
    await act(() => result.current.loadMore());
    expect(read).toHaveBeenCalledTimes(3);
    expect(read.mock.lastCall?.[0].cursor).toBeUndefined();
    expect(result.current.items.map(row => row.membershipId)).toEqual([1]);
  });
  it("aborts outdated group/date reads and ignores their response", async () => {
    const old = deferred<ReturnType<typeof page>>();
    read.mockReturnValueOnce(old.promise);
    const {
      result,
      rerender,
      unmount
    } = renderHook(({
      id,
      date
    }) => useWatchlistItemsController(id, date), {
      initialProps: {
        id: 1,
        date: "2026-09-01"
      }
    });
    rerender({
      id: 2,
      date: "2026-09-02"
    });
    await waitFor(() => expect(result.current.viewState).toBe("ready"));
    expect(read.mock.calls[0][1]?.signal?.aborted).toBe(true);
    await act(async () => old.resolve(page([item(99)])));
    expect(result.current.items.map(row => row.membershipId)).toEqual([1]);
    expect(read.mock.lastCall?.[0]).toMatchObject({
      groupId: 2,
      tradeDate: "2026-09-02"
    });
    const abandoned = deferred<ReturnType<typeof page>>();
    read.mockReturnValueOnce(abandoned.promise);
    act(() => {
      void result.current.reload();
    });
    unmount();
    expect(read.mock.lastCall?.[1]?.signal?.aborted).toBe(true);
    await act(async () => abandoned.resolve(page([item(100)])));
  });
  it("retains successful add evidence and sort when coordinated GET fails; does not append or repeat PUT", async () => {
    const {
      result
    } = renderHook(() => useWatchlistItemsController(1));
    await waitFor(() => expect(result.current.viewState).toBe("ready"));
    act(() => result.current.setSort("price"));
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    vi.mocked(api.addWatchlistGroupItem).mockResolvedValue({
      groupId: 1,
      tsCode: "000002.SZ",
      isAdded: true,
      created: true,
      memberCount: 2
    });
    await act(() => result.current.addToCurrentGroup("000002.SZ"));
    expect(read).toHaveBeenCalledTimes(2);
    expect(result.current.items).toHaveLength(1);
    read.mockRejectedValueOnce(new Error("刷新失败"));
    await act(() => result.current.reload());
    expect(result.current.mutation.kind).toBe("succeeded");
    expect(result.current.viewState).toBe("error");
    await act(() => result.current.reload());
    expect(read.mock.lastCall?.[0]).toMatchObject({
      sortBy: "price",
      direction: "desc"
    });
    expect(api.addWatchlistGroupItem).toHaveBeenCalledTimes(1);
  });
  it("resumes an interrupted initial read after a definite add failure", async () => {
    const old = deferred<ReturnType<typeof page>>();
    read.mockReturnValueOnce(old.promise);
    vi.mocked(api.addWatchlistGroupItem).mockRejectedValue(new api.WatchlistApiError("不能添加", "WL_WRITE_FAILED"));
    const {
      result
    } = renderHook(() => useWatchlistItemsController(1));
    await act(async () => {
      await result.current.addToCurrentGroup("000002.SZ").catch(() => {});
    });
    await waitFor(() => expect(result.current.viewState).toBe("ready"));
    expect(result.current.mutation.kind).toBe("failed");
    expect(read.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });
  it("ignores an old group's write response after A to B to A navigation", async () => {
    const {
      result,
      rerender
    } = renderHook(({
      id
    }) => useWatchlistItemsController(id), {
      initialProps: {
        id: 1
      }
    });
    await waitFor(() => expect(result.current.viewState).toBe("ready"));
    const pending = deferred<Awaited<ReturnType<typeof api.addWatchlistGroupItem>>>();
    vi.mocked(api.addWatchlistGroupItem).mockReturnValueOnce(pending.promise);
    let write!: ReturnType<typeof result.current.addToCurrentGroup>;
    act(() => {
      write = result.current.addToCurrentGroup("000002.SZ");
    });
    rerender({
      id: 2
    });
    await waitFor(() => expect(result.current.viewState).toBe("ready"));
    rerender({
      id: 1
    });
    await waitFor(() => expect(result.current.viewState).toBe("ready"));
    await act(async () => {
      pending.resolve({
        groupId: 1,
        tsCode: "000002.SZ",
        isAdded: true,
        created: true,
        memberCount: 2
      });
      expect(await write).toBeNull();
    });
    expect(result.current.mutation.kind).toBe("idle");
    expect(result.current.items.map(row => row.membershipId)).toEqual([1]);
  });
});
