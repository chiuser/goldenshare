import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WatchlistPage } from "./WatchlistPage";
import { AuthProvider } from "../../features/auth/model/AuthProvider";
import { WealthRouter } from "../../app/routes/WealthRouter";
import {
  deferred,
  item,
  page,
} from "../../features/watchlist/test/watchlistFixtures";

let intersect: IntersectionObserverCallback;
beforeEach(() => {
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      constructor(callback: IntersectionObserverCallback) {
        intersect = callback;
      }
      observe() {}
      disconnect() {}
      unobserve() {}
    },
  );
});
afterEach(() => {
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/wealth/market/overview");
});
function mockPage(value = page()) {
  const fetch = vi.fn(
    async (input: RequestInfo | URL, _options?: RequestInit) => {
      if (new URL(String(input)).pathname === "/api/v1/wealth/market/watchlist")
        return new Response(JSON.stringify(value));
      return new Response("{}", { status: 503 });
    },
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}
describe("watchlist page", () => {
  it("renders the approved columns, units, independent colors and freezing classes without homepage search", async () => {
    mockPage();
    render(<WatchlistPage search="?tradeDate=2026-09-02" />);
    const table = await screen.findByRole("table", { name: "自选股票列表" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual([
      "股票代码",
      "股票名称",
      "最新价（元）",
      "涨跌幅（%）",
      "成交量（万手）",
      "市盈率（PE TTM）",
      "市净率（PB）",
      "量比",
      "换手率（%）",
      "资金净流入（万）",
      "所属板块",
      "操作",
    ]);
    const cells = within(table).getAllByRole("cell");
    expect(cells.map((cell) => cell.textContent)).toEqual([
      "000001.SZ",
      "股票1",
      "12.34",
      "+1.73",
      "123.46",
      "5.62",
      "0.71",
      "1.08",
      "0.92",
      "-2189.40",
      "银行",
      "移除",
    ]);
    expect(cells[2]).toHaveClass("up");
    expect(cells[3]).toHaveClass("up");
    expect(cells[9]).toHaveClass("down");
    expect(cells[5]).toHaveClass("pe-column");
    expect(cells[6]).toHaveClass("pb-column");
    expect(
      table.querySelector(".valuation-column, .watchlist-valuation"),
    ).toBeNull();
    expect(cells[0]).toHaveClass("stock-code-column");
    expect(cells[1]).toHaveClass("stock-name-column");
    expect(cells[11]).toHaveClass("action-column");
    expect(cells[10]).toHaveClass("sector-column");
    expect(cells[10]).not.toHaveClass("action-column");
    expect(screen.getByLabelText("自选股票滚动区域")).toHaveClass(
      "watchlist-table-scroll",
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "000001.SZ" }));
    expect(window.location.pathname).toBe("/wealth/market/stock/000001.SZ");
  });
  it("renders sector labels without decorating missing industries", async () => {
    mockPage(
      page([
        item(1),
        item(2, { stock: { ...item(2).stock, industry: null } }),
      ]),
    );
    render(<WatchlistPage />);
    const table = await screen.findByRole("table", { name: "自选股票列表" });
    const sector = within(table).getByText("银行");
    expect(sector).toHaveClass("watchlist-sector-tag");
    expect(sector).toHaveAttribute("title", "银行");
    const missing = table.querySelector(".watchlist-sector-empty");
    expect(missing).toHaveTextContent("--");
    expect(missing).not.toHaveClass("watchlist-sector-tag");
    expect(table.querySelectorAll(".watchlist-sector-tag")).toHaveLength(1);
    expect(missing?.closest(".sector-column")?.querySelector("button")).toBeNull();
  });
  it("keeps full long sector names available without adding a label action", async () => {
    const industry = "电力设备与新能源材料";
    mockPage(page([item(1, { stock: { ...item(1).stock, industry } })]));
    render(<WatchlistPage />);
    const sector = await screen.findByText(industry);
    expect(sector).toHaveClass("watchlist-sector-tag");
    expect(sector).toHaveAttribute("title", industry);
    expect(sector.tagName).toBe("SPAN");
    expect(sector).not.toHaveAttribute("role");
    fireEvent.click(sector);
    expect(window.location.pathname).toBe("/wealth/market/stock/000001.SZ");
    expect(window.location.search).not.toContain("period=");
  });
  it.each([
    ["UP", 1.73, "up"],
    ["DOWN", -1.73, "down"],
    ["FLAT", 0, "flat"],
    ["UNKNOWN", null, "watchlist-missing"],
  ] as const)(
    "uses the same %s price and change color",
    async (direction, changePct, className) => {
      mockPage(
        page([
          item(1, {
            quote: { price: 12.34, changePct, direction, vol: 1234567 },
          }),
        ]),
      );
      render(<WatchlistPage />);
      const table = await screen.findByRole("table", { name: "自选股票列表" });
      const cells = within(table).getAllByRole("cell");
      expect(cells[2]).toHaveClass(className);
      expect(cells[3]).toHaveClass(className);
    },
  );
  it("keeps missing price neutral even with a known rising change", async () => {
    mockPage(
      page([
        item(1, {
          quote: {
            price: null,
            changePct: 1.73,
            direction: "UP",
            vol: 1234567,
          },
          valuation: { peTtm: null, pb: 0.71 },
        }),
      ]),
    );
    render(<WatchlistPage />);
    const table = await screen.findByRole("table", { name: "自选股票列表" });
    const cells = within(table).getAllByRole("cell");
    expect(cells[2]).toHaveTextContent("--");
    expect(cells[2]).toHaveClass("watchlist-missing");
    expect(cells[2]).not.toHaveClass("up");
    expect(cells[3]).toHaveClass("up");
    expect(cells[5]).toHaveTextContent("--");
    expect(cells[6]).toHaveTextContent("0.71");
  });
  it.each(["DELAYED", "PARTIAL"] as const)(
    "keeps rows for %s and shows missing valuation as --",
    async (status) => {
      mockPage(
        page(
          [
            item(1, {
              valuation: { peTtm: null, pb: -1 },
              quote: {
                price: null,
                changePct: 0,
                direction: "FLAT",
                vol: null,
              },
            }),
          ],
          {
            dataStatus: {
              status,
              observedTradeDate: "2026-09-01",
              expectedTradeDate: "2026-09-02",
            },
          },
        ),
      );
      render(<WatchlistPage />);
      const table = await screen.findByRole("table", { name: "自选股票列表" });
      expect(screen.getByText("2026-09-01")).toBeInTheDocument();
      expect(within(table).getAllByText("--").length).toBeGreaterThan(2);
      expect(within(table).getByText("0.00").parentElement).toHaveClass("flat");
      expect(screen.getByRole("status")).toHaveTextContent(
        status === "PARTIAL" ? "部分数据缺失" : "行情数据延迟",
      );
    },
  );
  it("covers loading, empty and error with retry; empty opens a blank add dialog", async () => {
    const pending = deferred<Response>();
    const fetch = vi
      .fn()
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValue(new Response("{}", { status: 503 }));
    vi.stubGlobal("fetch", fetch);
    render(<WatchlistPage />);
    expect(screen.getByLabelText("自选加载中")).toBeInTheDocument();
    await act(async () => pending.resolve(new Response("{}", { status: 500 })));
    expect(screen.getByRole("alert")).toHaveTextContent("自选列表暂不可用");
    fetch.mockResolvedValueOnce(new Response(JSON.stringify(page([]))));
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("还没有自选股票")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+ 添加第一只自选股" }));
    expect(screen.getByRole("dialog", { name: "添加自选" })).toHaveAttribute(
      "open",
    );
    expect(screen.getByRole("rowgroup")).toBeEmptyDOMElement();
  });
  it("loads to the final cursor, removes only after confirmation and does not navigate from removal", async () => {
    const fetch = mockPage(page([item(1)], { totalCount: 2, nextCursor: 1 }));
    render(<WatchlistPage />);
    await screen.findByRole("table", { name: "自选股票列表" });
    fetch.mockResolvedValueOnce(
      new Response(JSON.stringify(page([item(2)], { totalCount: 2 }))),
    );
    act(() =>
      intersect(
        [{ isIntersecting: true }] as IntersectionObserverEntry[],
        {} as IntersectionObserver,
      ),
    );
    await screen.findByText("股票2");
    expect(screen.queryByText("向下滚动加载更多")).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "移除 股票1 000001.SZ" }),
    );
    expect(window.location.pathname).not.toContain("/stock/");
    expect(screen.getByRole("dialog")).toHaveAccessibleName(
      "确认移除「股票1」？",
    );
    expect(
      fetch.mock.calls.filter(
        ([, options]) => (options as RequestInit)?.method === "DELETE",
      ),
    ).toHaveLength(0);
    fetch.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          tsCode: "000001.SZ",
          isAdded: false,
          removed: true,
          totalCount: 1,
        }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "确认移除" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "000001.SZ" }),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByText("1 只")).toBeInTheDocument();
  });
  it("matches the authenticated watchlist route before the homepage fallback", async () => {
    mockPage(page([]));
    window.history.replaceState({}, "", "/wealth/market/watchlist");
    render(
      <AuthProvider>
        <WealthRouter />
      </AuthProvider>,
    );
    expect(await screen.findByText("还没有自选股票")).toBeInTheDocument();
  });
});
