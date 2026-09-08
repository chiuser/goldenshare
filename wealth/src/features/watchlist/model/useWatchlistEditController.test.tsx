import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/watchlistApi";
import { useWatchlistEditController } from "./useWatchlistEditController";
vi.mock("../api/watchlistApi", async original => ({
  ...(await original<typeof import("../api/watchlistApi")>()),
  batchWatchlistItems: vi.fn()
}));
beforeEach(() => vi.resetAllMocks());
describe("edit controller", () => {
  it("enforces loaded-only 0/200/201 selection, keeps selected IDs when loading more, allows deselect/reselect, and Done never writes", async () => {
    const ids = Array.from({
      length: 201
    }, (_, i) => i + 1);
    const {
      result,
      rerender
    } = renderHook(({
      loaded
    }) => useWatchlistEditController(1, loaded, 200), {
      initialProps: {
        loaded: ids.slice(0, 200)
      }
    });
    act(() => result.current.enter());
    await act(() => result.current.submit("PIN"));
    expect(api.batchWatchlistItems).not.toHaveBeenCalled();
    act(() => {
      for (const id of ids) result.current.toggle(id);
    });
    expect(result.current.selectedIds.size).toBe(200);
    expect(result.current.selectedIds.has(201)).toBe(false);
    rerender({
      loaded: ids
    });
    act(() => result.current.toggle(201));
    expect(result.current.selectedIds.size).toBe(200);
    act(() => result.current.toggle(1));
    act(() => result.current.toggle(201));
    expect(result.current.selectedIds.size).toBe(200);
    expect(result.current.selectedIds.has(201)).toBe(true);
    act(() => result.current.finish());
    expect(result.current.isEditing).toBe(false);
    expect(result.current.selectedIds.size).toBe(0);
    expect(api.batchWatchlistItems).not.toHaveBeenCalled();
  });
  it.each(["MOVE", "ADD_TO_GROUPS", "REMOVE", "PIN", "UNPIN"] as const)("owns %s once and clears selection/dialog but remains editing after success", async action => {
    vi.mocked(api.batchWatchlistItems).mockResolvedValue({
      action,
      requestedCount: 1,
      createdCount: 0,
      removedCount: 0,
      updatedCount: 1,
      groupCounts: [{
        groupId: 1,
        memberCount: 1
      }]
    });
    const {
      result
    } = renderHook(() => useWatchlistEditController(1, [7], 200));
    act(() => result.current.enter());
    act(() => {
      result.current.toggle(7);
      result.current.setDialog("move");
    });
    await act(() => result.current.submit(action, [2]));
    expect(api.batchWatchlistItems).toHaveBeenCalledExactlyOnceWith(1, action, [7], [2]);
    expect(result.current.selectedIds.size).toBe(0);
    expect(result.current.dialog).toBeNull();
    expect(result.current.isEditing).toBe(true);
  });
  it.each(["WL_WRITE_FAILED", "WL_SELECTION_STALE", "WL_WRITE_OUTCOME_UNKNOWN"])("distinguishes %s without replay", async code => {
    vi.mocked(api.batchWatchlistItems).mockRejectedValue(new api.WatchlistApiError("失败", code, code === "WL_WRITE_OUTCOME_UNKNOWN" ? "UNKNOWN" : "FAILED"));
    const {
      result
    } = renderHook(() => useWatchlistEditController(1, [7], 200));
    act(() => result.current.enter());
    act(() => {
      result.current.toggle(7);
      result.current.setDialog("remove");
    });
    await act(async () => {
      await result.current.submit("REMOVE").catch(() => {});
    });
    expect(result.current.selectedIds.size).toBe(code === "WL_SELECTION_STALE" ? 0 : 1);
    expect(result.current.mutation.kind).toBe(code === "WL_WRITE_OUTCOME_UNKNOWN" ? "unknown" : "failed");
    expect(api.batchWatchlistItems).toHaveBeenCalledTimes(1);
    if (code === "WL_WRITE_OUTCOME_UNKNOWN") {
      await act(() => result.current.submit("REMOVE"));
      expect(api.batchWatchlistItems).toHaveBeenCalledTimes(1);
      act(() => result.current.reconciled());
      expect(result.current.selectedIds.size).toBe(0);
      expect(result.current.mutation.kind).toBe("idle");
    }
  });
});
