import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/watchlistApi";
import { deferred, group, rules } from "../test/watchlistFixtures";
import { useWatchlistGroupsController } from "./useWatchlistGroupsController";
vi.mock("../api/watchlistApi", async original => ({
  ...(await original<typeof import("../api/watchlistApi")>()),
  fetchWatchlistGroups: vi.fn(),
  createWatchlistGroup: vi.fn(),
  changeWatchlistGroupColor: vi.fn(),
  deleteWatchlistGroup: vi.fn()
}));
const read = vi.mocked(api.fetchWatchlistGroups);
beforeEach(() => {
  vi.resetAllMocks();
  read.mockResolvedValue({
    groups: [group(), group(2), group(3)],
    rules
  });
});
describe("groups controller", () => {
  it("selects default, refuses editing switches, activates the server create/delete target after one coordinated read", async () => {
    const {
      result
    } = renderHook(useWatchlistGroupsController);
    await waitFor(() => expect(result.current.currentGroupId).toBe(1));
    act(() => result.current.selectGroup(2, true));
    expect(result.current.currentGroupId).toBe(1);
    vi.mocked(api.createWatchlistGroup).mockResolvedValue({
      group: group(4)
    });
    await act(() => result.current.submit({
      type: "create",
      name: "分组4",
      color: rules.palette[0]
    }));
    expect(read).toHaveBeenCalledTimes(1);
    read.mockResolvedValue({
      groups: [group(), group(2), group(3), group(4)],
      rules
    });
    await act(() => result.current.refresh());
    expect(result.current.currentGroupId).toBe(4);
    vi.mocked(api.deleteWatchlistGroup).mockResolvedValue({
      deletedGroupId: 4,
      deletedMemberCount: 0,
      nextGroupId: 1
    });
    await act(() => result.current.submit({
      type: "delete",
      groupId: 4
    }));
    read.mockResolvedValue({
      groups: [group(), group(2), group(3)],
      rules
    });
    await act(() => result.current.refresh());
    expect(result.current.currentGroupId).toBe(1);
    expect(api.deleteWatchlistGroup).toHaveBeenCalledTimes(1);
  });
  it("falls back from a disappeared group and discards a superseded groups read", async () => {
    const {
      result,
      unmount
    } = renderHook(useWatchlistGroupsController);
    await waitFor(() => expect(result.current.currentGroupId).toBe(1));
    act(() => result.current.selectGroup(3, false));
    const old = deferred<Awaited<ReturnType<typeof api.fetchWatchlistGroups>>>();
    read.mockReturnValueOnce(old.promise).mockResolvedValueOnce({
      groups: [group()],
      rules
    });
    let pending!: ReturnType<typeof result.current.refresh>;
    act(() => {
      pending = result.current.refresh();
    });
    await act(() => result.current.refresh());
    await act(async () => {
      old.resolve({
        groups: [group(), group(3)],
        rules
      });
      await pending;
    });
    expect(result.current.currentGroupId).toBe(1);
    expect(read.mock.calls[1][0]?.signal?.aborted).toBe(true);
    unmount();
    expect(read.mock.calls[2][0]?.signal?.aborted).toBe(true);
  });
  it("keeps successful write evidence after GET fails, never replays it, and does not guess a missing default", async () => {
    const {
      result
    } = renderHook(useWatchlistGroupsController);
    await waitFor(() => expect(result.current.currentGroupId).toBe(1));
    vi.mocked(api.changeWatchlistGroupColor).mockResolvedValue({
      group: group(2, {
        color: rules.palette[1]
      })
    });
    await act(() => result.current.submit({
      type: "color",
      groupId: 2,
      color: rules.palette[1]
    }));
    read.mockRejectedValueOnce(new Error("读取失败"));
    await act(() => result.current.refresh());
    expect(result.current.mutation.kind).toBe("succeeded");
    expect(result.current.state.kind).toBe("error");
    read.mockResolvedValue({
      groups: [group(2)],
      rules
    });
    await act(() => result.current.refresh());
    expect(result.current.state.kind).toBe("error");
    expect(api.changeWatchlistGroupColor).toHaveBeenCalledTimes(1);
    expect(api.createWatchlistGroup).not.toHaveBeenCalled();
  });
  it("owns a single pending or unknown action and only a facts reconciliation unlocks it", async () => {
    const pending = deferred<Awaited<ReturnType<typeof api.createWatchlistGroup>>>();
    vi.mocked(api.createWatchlistGroup).mockReturnValue(pending.promise);
    const {
      result
    } = renderHook(useWatchlistGroupsController);
    await waitFor(() => expect(result.current.currentGroupId).toBe(1));
    const action = {
      type: "create" as const,
      name: "成长",
      color: rules.palette[0]
    };
    let write!: Promise<unknown>;
    act(() => {
      write = result.current.submit(action).catch(error => error);
    });
    await act(() => result.current.submit(action));
    expect(api.createWatchlistGroup).toHaveBeenCalledTimes(1);
    await act(async () => {
      pending.reject(new api.WatchlistApiError("待确认", "WL_WRITE_OUTCOME_UNKNOWN", "UNKNOWN"));
      await write;
    });
    expect(result.current.mutation).toMatchObject({
      kind: "unknown",
      action
    });
    await act(() => result.current.submit(action));
    expect(api.createWatchlistGroup).toHaveBeenCalledTimes(1);
    await act(() => result.current.refresh());
    act(() => result.current.reconciled());
    expect(result.current.mutation.kind).toBe("idle");
  });
});
