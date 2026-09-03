import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { searchWatchlistCandidates } from "../api/watchlistApi";
import type { WatchlistSearchResponseDto } from "../api/watchlistApiTypes";
import { deferred } from "../test/watchlistFixtures";
import { AddWatchlistDialog } from "./AddWatchlistDialog";

vi.mock("../api/watchlistApi", async (original) => ({
  ...(await original<typeof import("../api/watchlistApi")>()),
  searchWatchlistCandidates: vi.fn(),
}));
const search = vi.mocked(searchWatchlistCandidates);
const candidates: WatchlistSearchResponseDto = {
  keyword: "PAYH",
  items: [
    { tsCode: "000001.SZ", name: "平安银行", status: "AVAILABLE" },
    { tsCode: "600000.SH", name: "浦发银行", status: "ADDED" },
  ],
};
beforeEach(() => {
  vi.useFakeTimers();
  vi.resetAllMocks();
  search.mockResolvedValue(candidates);
});
afterEach(() => vi.useRealTimers());
const pause = () => act(() => vi.advanceTimersByTimeAsync(500));
describe("add watchlist dialog", () => {
  it("opens empty with a fixed results area, then renders three columns after exactly 500 ms", async () => {
    const onAdd = vi.fn().mockResolvedValue({});
    const props = {
      open: true,
      onClose: vi.fn(),
      onAdd,
      pendingCodes: [],
      memberships: {},
    };
    const { rerender } = render(<AddWatchlistDialog {...props} />);
    expect(screen.getByRole("dialog")).toHaveAttribute("open");
    const input = screen.getByPlaceholderText("输入名称首字母或代码");
    expect(screen.getByRole("rowgroup")).toBeEmptyDOMElement();
    expect(screen.getByRole("rowgroup")).toHaveClass("watchlist-search-body");
    expect(
      screen.getAllByRole("columnheader").map((node) => node.textContent),
    ).toEqual(["代码", "名称", "状态"]);
    expect(search).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: "PAYH" } });
    await act(() => vi.advanceTimersByTimeAsync(499));
    expect(search).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(search).toHaveBeenCalledTimes(1);
    expect(screen.getByText("已添加")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "添加 平安银行 000001.SZ" }),
    );
    await act(async () => {});
    expect(onAdd).toHaveBeenCalledWith("000001.SZ");
    expect(screen.getByRole("dialog")).toHaveAttribute("open");
    expect(screen.getByText("已添加到列表末尾")).toBeInTheDocument();
    rerender(
      <AddWatchlistDialog {...props} memberships={{ "000001.SZ": true }} />,
    );
    expect(screen.getAllByText("已添加")).toHaveLength(2);
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByRole("rowgroup")).toBeEmptyDOMElement();
    await pause();
    expect(search).toHaveBeenCalledTimes(1);
  });
  it("cancels old searches, suppresses out-of-order responses, resets on close, and respects IME", async () => {
    const old = deferred<WatchlistSearchResponseDto>();
    search
      .mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce({ keyword: "NEW", items: [] });
    const props = {
      open: true,
      onClose: vi.fn(),
      onAdd: vi.fn(),
      pendingCodes: [],
      memberships: {},
    };
    const { rerender } = render(<AddWatchlistDialog {...props} />);
    const input = screen.getByRole("textbox");
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "PAYH" } });
    await pause();
    expect(search).not.toHaveBeenCalled();
    fireEvent.compositionEnd(input);
    await pause();
    expect(screen.getByText("正在搜索…")).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "NEW" } });
    expect(search.mock.calls[0][1]?.signal?.aborted).toBe(true);
    await pause();
    await act(async () => old.resolve(candidates));
    expect(screen.queryByText("平安银行")).not.toBeInTheDocument();
    expect(screen.getByText("未找到匹配的当前上市 A 股")).toBeInTheDocument();
    rerender(<AddWatchlistDialog {...props} open={false} />);
    rerender(<AddWatchlistDialog {...props} />);
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(screen.getByRole("rowgroup")).toBeEmptyDOMElement();
  });
  it("preserves input on failure, retries search, and disables only the pending candidate", async () => {
    search.mockRejectedValueOnce(new Error("搜索失败"));
    render(
      <AddWatchlistDialog
        open
        onClose={vi.fn()}
        onAdd={vi.fn()}
        pendingCodes={["000001.SZ"]}
        memberships={{}}
      />,
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "PAYH" },
    });
    await pause();
    expect(screen.getByRole("alert")).toHaveTextContent("搜索失败");
    expect(screen.getByRole("textbox")).toHaveValue("PAYH");
    fireEvent.click(
      within(screen.getByRole("alert")).getByRole("button", { name: "重试" }),
    );
    await pause();
    expect(
      screen.getByRole("button", { name: "添加 平安银行 000001.SZ" }),
    ).toBeDisabled();
    expect(screen.getByRole("button", { name: "完成" })).toBeEnabled();
  });
});
