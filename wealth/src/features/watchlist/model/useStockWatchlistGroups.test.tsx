import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../api/watchlistApi";
import { deferred, group } from "../test/watchlistFixtures";
import { StockWatchlistGroupPicker } from "../ui/StockWatchlistGroupPicker";
import { useStockWatchlistGroups } from "./useStockWatchlistGroups";
vi.mock("../api/watchlistApi", async original => ({
  ...(await original<typeof import("../api/watchlistApi")>()),
  fetchStockWatchlistGroups: vi.fn(),
  replaceStockWatchlistGroups: vi.fn()
}));
const read = vi.mocked(api.fetchStockWatchlistGroups);
function facts(tsCode = "000001.SZ", ids: number[] = [], count = 2) {
  return {
    tsCode,
    isAdded: ids.length > 0,
    groups: Array.from({
      length: count
    }, (_, index) => {
      const g = group(index + 1);
      return {
        groupId: g.id,
        name: g.name,
        isDefault: g.isDefault,
        color: g.color,
        selected: ids.includes(g.id)
      };
    })
  };
}
beforeEach(() => {
  vi.resetAllMocks();
  read.mockImplementation(async code => facts(code));
});
function Picker() {
  const controller = useStockWatchlistGroups("000001.SZ", true);
  return <StockWatchlistGroupPicker controller={controller} />;
}
describe("stock group picker", () => {
  it("reads on every open, separates draft and committed, forbids empty selection and never forces the default", async () => {
    const {
      result
    } = renderHook(() => useStockWatchlistGroups("000001.SZ", true));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    act(() => result.current.show());
    await waitFor(() => expect(read).toHaveBeenCalledTimes(2));
    await act(() => result.current.confirm());
    expect(api.replaceStockWatchlistGroups).not.toHaveBeenCalled();
    act(() => result.current.toggle(2));
    expect(result.current.isAdded).toBe(false);
    expect([...result.current.draftIds]).toEqual([2]);
    vi.mocked(api.replaceStockWatchlistGroups).mockResolvedValue({
      tsCode: "000001.SZ",
      isAdded: true,
      groupIds: [2],
      createdCount: 1,
      removedCount: 0
    });
    await act(() => result.current.confirm());
    expect(api.replaceStockWatchlistGroups).toHaveBeenCalledExactlyOnceWith("000001.SZ", [2]);
    expect(result.current.open).toBe(false);
    expect(result.current.isAdded).toBe(true);
    read.mockResolvedValue(facts("000001.SZ", [1]));
    act(() => result.current.show());
    await waitFor(() => expect([...result.current.draftIds]).toEqual([1]));
    expect(read).toHaveBeenCalledTimes(3);
  });
  it.each(["取消", "Escape", "outside"])("%s cancels the draft, returns focus and issues zero writes", async close => {
    render(<Picker />);
    const button = screen.getByRole("button", {
      name: "+自选"
    });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    const check = await screen.findByRole("checkbox", {
      name: "分组2"
    });
    fireEvent.click(check);
    if (close === "取消") fireEvent.click(screen.getByRole("button", {
      name: "取消"
    }));else if (close === "Escape") fireEvent.keyDown(document, {
      key: "Escape"
    });else fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(button).toHaveFocus();
    expect(api.replaceStockWatchlistGroups).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(await screen.findByRole("checkbox", {
      name: "分组2"
    })).not.toBeChecked();
  });
  it.each([1, 2, 10])("renders exactly %s natural rows with no six-row placeholder or scroll container", async count => {
    read.mockResolvedValue(facts("000001.SZ", [1], count));
    render(<Picker />);
    fireEvent.click(await screen.findByRole("button", {
      name: "已添加"
    }));
    await waitFor(() => expect(screen.getAllByRole("checkbox")).toHaveLength(count));
    const list = screen.getAllByRole("checkbox")[0].closest(".watchlist-group-options") as HTMLElement;
    expect(list.style.height).toBe("");
    expect(list.style.maxHeight).toBe("");
    expect(["auto", "scroll"]).not.toContain(getComputedStyle(list).overflowY);
    expect(screen.getAllByRole("checkbox")[0]).toHaveAccessibleName("我的自选");
  });
  it("can close during GET and reopen; late reads never reopen or overwrite later drafts", async () => {
    const {
      result
    } = renderHook(() => useStockWatchlistGroups("000001.SZ", true));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    const old = deferred<ReturnType<typeof facts>>();
    read.mockReturnValueOnce(old.promise);
    act(() => result.current.show());
    act(() => result.current.cancel());
    expect(result.current.status).toBe("ready");
    expect(read.mock.calls[1][1]?.signal?.aborted).toBe(true);
    act(() => result.current.show());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    act(() => result.current.toggle(2));
    await act(async () => old.resolve(facts("000001.SZ", [1])));
    expect([...result.current.draftIds]).toEqual([2]);
  });
  it("preserves drafts on definite failure, locks pending close and clears no membership optimistically", async () => {
    read.mockResolvedValue(facts("000001.SZ", [2]));
    const pending = deferred<Awaited<ReturnType<typeof api.replaceStockWatchlistGroups>>>();
    vi.mocked(api.replaceStockWatchlistGroups).mockReturnValue(pending.promise);
    const {
      result
    } = renderHook(() => useStockWatchlistGroups("000001.SZ", true));
    await waitFor(() => expect(result.current.isAdded).toBe(true));
    act(() => result.current.show());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    act(() => result.current.toggle(1));
    let saving!: Promise<void>;
    act(() => {
      saving = result.current.confirm();
    });
    act(() => result.current.cancel());
    expect(result.current.open).toBe(true);
    expect([...result.current.committedIds]).toEqual([2]);
    await act(async () => {
      pending.reject(new api.WatchlistApiError("明确失败", "WL_WRITE_FAILED"));
      await saving;
    });
    expect(result.current.mutation.kind).toBe("failed");
    expect([...result.current.draftIds]).toEqual([2, 1]);
  });
  it("automatically reads after an uncertain PUT, retries GET only after read failure and rebuilds the draft", async () => {
    const {
      result
    } = renderHook(() => useStockWatchlistGroups("000001.SZ", true));
    await waitFor(() => expect(result.current.status).toBe("ready"));
    act(() => result.current.show());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    act(() => result.current.toggle(2));
    vi.mocked(api.replaceStockWatchlistGroups).mockRejectedValue(new api.WatchlistApiError("待确认", "WL_WRITE_OUTCOME_UNKNOWN", "UNKNOWN"));
    read.mockRejectedValueOnce(new Error("读取失败"));
    await act(() => result.current.confirm());
    expect(result.current.mutation.kind).toBe("unknown");
    expect(result.current.status).toBe("error");
    expect(result.current.open).toBe(true);
    await act(() => result.current.confirm());
    expect(api.replaceStockWatchlistGroups).toHaveBeenCalledTimes(1);
    read.mockResolvedValue(facts("000001.SZ", [1]));
    await act(() => result.current.retry());
    expect(result.current.mutation.kind).toBe("idle");
    expect([...result.current.draftIds]).toEqual([1]);
  });
  it("ignores an old stock write even after A to B to A navigation", async () => {
    const {
      result,
      rerender
    } = renderHook(({
      code
    }) => useStockWatchlistGroups(code, true), {
      initialProps: {
        code: "000001.SZ"
      }
    });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    act(() => result.current.show());
    await waitFor(() => expect(result.current.status).toBe("ready"));
    act(() => result.current.toggle(2));
    const pending = deferred<Awaited<ReturnType<typeof api.replaceStockWatchlistGroups>>>();
    vi.mocked(api.replaceStockWatchlistGroups).mockReturnValue(pending.promise);
    let saving!: Promise<void>;
    act(() => {
      saving = result.current.confirm();
    });
    rerender({
      code: "000002.SZ"
    });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    rerender({
      code: "000001.SZ"
    });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    await act(async () => {
      pending.resolve({
        tsCode: "000001.SZ",
        isAdded: true,
        groupIds: [2],
        createdCount: 1,
        removedCount: 0
      });
      await saving;
    });
    expect(result.current.isAdded).toBe(false);
    expect(result.current.mutation.kind).toBe("idle");
    expect(result.current.open).toBe(false);
  });
});
