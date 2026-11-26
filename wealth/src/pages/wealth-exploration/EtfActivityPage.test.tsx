import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, expect, it, vi } from "vitest";

import { WealthRouter } from "../../app/routes/WealthRouter";
import { AuthProvider } from "../../features/auth/model/AuthProvider";
import type { EtfActivityResponse } from "../../features/wealth-exploration/etf-activity/api/etfActivityApi";
import { EtfActivityPage } from "./EtfActivityPage";

const API = "/api/v1/wealth/market/etf-activity";
const HEADERS = ["今日排名", "ETF 代码", "ETF 名称", "现价（元）", "涨跌幅", "成交额（亿元）", "较前一交易日"];

// DTO shape and real sample fields follow the independently checked API in LLD §3 and §8.
// The artificial gap and zero are deliberate display-only counterexamples.
const data: EtfActivityResponse = {
  tradeDate: "2026-11-25", previousTradeDate: "2026-11-24", oneMonthStartDate: "2026-10-25",
  trend: [
    { tradeDate: "2026-10-23", amountYuan: 400_000_000_000, ma5Yuan: 410_000_000_000, ma20Yuan: 420_000_000_000 },
    { tradeDate: "2026-11-20", amountYuan: 0, ma5Yuan: 10_000_000_000, ma20Yuan: 20_000_000_000 },
    { tradeDate: "2026-11-23", amountYuan: null, ma5Yuan: null, ma20Yuan: null },
    { tradeDate: "2026-11-24", amountYuan: 100_000_000_000, ma5Yuan: null, ma20Yuan: null },
    { tradeDate: "2026-11-25", amountYuan: 540_028_802_036, ma5Yuan: 558_434_645_419.22, ma20Yuan: 553_704_175_757.925 },
  ],
  ranking: { status: "ready", error: null, rows: [
    { rank: 1, tsCode: "511360.SH", name: "海富通中证短融ETF", closePrice: 114.199, priceChangePct: 0, amountYuan: 59_504_915_768, rankChange: 0 },
    { rank: 2, tsCode: "511880.SH", name: null, closePrice: 101.002, priceChangePct: 0.01, amountYuan: 22_683_463_848, rankChange: -4 },
    { rank: 3, tsCode: "510330.SH", name: "华夏沪深300ETF", closePrice: 4.136, priceChangePct: -1.57, amountYuan: 12_575_059_866, rankChange: 31 },
    { rank: 4, tsCode: "511990.SH", name: "华宝现金添益货币ETF-A", closePrice: 100.007, priceChangePct: -0.001, amountYuan: 12_371_000_000, rankChange: null },
  ] },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

function deferred<T>() {
  let resolve!: (result: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.useRealTimers();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/wealth/exploration");
});

it("uses the signed-in local route and one business request even under Strict Mode", async () => {
  vi.stubEnv("DEV", true);
  vi.stubEnv("MODE", "development");
  window.localStorage.setItem("wealth.auth.access-token", "local-test-session");
  window.history.replaceState({}, "", "/wealth/exploration/etf-activity?tradeDate=2000-01-01");
  const response = deferred<Response>();
  const fetchMock = vi.fn(() => response.promise);
  vi.stubGlobal("fetch", fetchMock);

  render(<StrictMode><AuthProvider><WealthRouter /></AuthProvider></StrictMode>);
  expect(screen.getByText("正在读取 ETF 日成交额…")).toBeInTheDocument();
  expect(screen.getByText("正在读取 ETF 榜单…")).toBeInTheDocument();
  expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(HEADERS);
  expect(screen.getByRole("button", { name: /查看 ETF 成交额趋势/ })).toHaveClass("selected");
  expect(screen.queryByLabelText("页面时间状态")).not.toBeInTheDocument();

  response.resolve(json(data));
  expect(await screen.findByText("华夏沪深300ETF")).toBeInTheDocument();
  expect(fetchMock).toHaveBeenCalledExactlyOnceWith(API, expect.objectContaining({
    method: "GET", headers: expect.any(Headers), signal: expect.any(AbortSignal),
  }));
  const calls = fetchMock.mock.calls as unknown as [string, RequestInit][];
  expect(new Headers(calls[0][1].headers).get("Authorization")).toBe("Bearer local-test-session");
  expect(within(screen.getByLabelText("Breadcrumb")).getByRole("button", { name: "财势探查" })).toBeInTheDocument();
});

it("keeps ranking order, position and selection when switching without fetching or recomputing", async () => {
  const fetchMock = vi.fn(async () => json(data));
  vi.stubGlobal("fetch", fetchMock);
  render(<EtfActivityPage />);
  const row = (await screen.findByText("华夏沪深300ETF")).closest("tr")!;
  expect(within(row).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
    "3", "510330.SH", "华夏沪深300ETF", "4.136", "−1.57%", "125.75", "↑ 31",
  ]);
  expect(within(row).getByText("−1.57%")).toHaveClass("down");
  expect(within(row).getByText("↑ 31")).toHaveClass("up");
  expect(screen.getByText("↓ 4")).toHaveClass("down");
  expect(screen.getByText("+0.01%")).toHaveClass("up");
  expect(screen.getByText("持平")).toHaveClass("flat");
  expect(screen.getAllByText("0.00%").every((cell) => cell.classList.contains("flat"))).toBe(true);
  expect(screen.getByText("日线收盘")).toHaveTextContent("2026-11-25");
  expect(screen.getByText("对比日")).toHaveTextContent("2026-11-24");

  const ranking = screen.getByRole("region", { name: "ETF 排行表体" });
  ranking.scrollTop = 117;
  const chart = screen.getByRole("group", { name: /ETF 日成交额趋势图/ });
  fireEvent.keyDown(chart, { key: "ArrowLeft" });
  expect(within(chart).getByRole("status")).toHaveTextContent("5400.29 亿");
  expect(within(chart).getByRole("status")).toHaveTextContent("5584.35 亿");
  expect(within(chart).getByRole("status")).toHaveTextContent("5537.04 亿");
  expect(screen.getByRole("button", { name: "1 个月" })).toHaveAttribute("aria-pressed", "true");
  const line = chart.querySelector('[data-series="amountYuan"]')!;
  const short = line.getAttribute("d");
  expect(short).toMatch(/^M56,325 M[\d.]+,[\d.]+ L/);
  expect(chart.querySelector(".etf-chart-zero")).toHaveAttribute("y1", "325");
  expect(within(chart).queryByText("10-23")).not.toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "3 个月" }));
  expect(within(chart).getByText("10-23")).toBeInTheDocument();
  expect(line.getAttribute("d")).not.toBe(short);
  expect(within(chart).getByRole("status")).toHaveTextContent("2026-11-25");
  expect(screen.getByRole("region", { name: "ETF 排行表体" })).toBe(ranking);
  expect(ranking.scrollTop).toBe(117);
  expect((await screen.findByText("华夏沪深300ETF")).closest("tr")).toBe(row);
  expect(fetchMock).toHaveBeenCalledOnce();

  fireEvent.keyDown(chart, { key: "ArrowLeft" });
  expect(within(chart).getByRole("status")).toHaveTextContent("2026-11-24");
  expect(within(chart).getByRole("status")).toHaveTextContent("1000.00 亿");
  expect(within(chart).getAllByText("—")).toHaveLength(2);
});

it.each(["2026-11-24", null])("keeps the current-day price and ranking in partial state (%s)", async (previousTradeDate) => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ ...data, previousTradeDate,
    ranking: { status: "partial", error: null, rows: [{ ...data.ranking.rows[2], rankChange: null }] },
  })));
  render(<EtfActivityPage />);
  const row = (await screen.findByText("华夏沪深300ETF")).closest("tr")!;
  expect(within(row).getByText("−1.57%")).toBeInTheDocument();
  expect(within(row).getByText("—")).toBeInTheDocument();
  expect(screen.queryByText("对比日")).not.toBeInTheDocument();
  expect(screen.getByText(previousTradeDate ? /前一交易日（2026-11-24）日线暂缺/ : "暂无前一交易日可供比较")).toBeInTheDocument();
});

it("keeps the trend and its selection during ranking retry, then updates both panels from one response", async () => {
  const failed = { ...data, ranking: { rows: [], status: "error", error: {
    code: "ETF_ACTIVITY_RANKING_UNAVAILABLE", message: "ETF 排行榜暂不可读取，请重试",
  } } };
  const retried = deferred<Response>();
  const fetchMock = vi.fn().mockResolvedValueOnce(json(failed)).mockImplementationOnce(() => retried.promise);
  vi.stubGlobal("fetch", fetchMock);
  render(<EtfActivityPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("ETF 排行榜暂不可读取，请重试");
  fireEvent.click(screen.getByRole("button", { name: "3 个月" }));
  const chart = screen.getByRole("group", { name: /ETF 日成交额趋势图/ });
  fireEvent.keyDown(chart, { key: "ArrowRight" });
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(screen.getByRole("button", { name: "正在重试…" })).toBeDisabled();
  expect(within(chart).getByRole("status")).toHaveTextContent("2026-11-25");
  retried.resolve(json({ ...data, tradeDate: "2026-11-26", previousTradeDate: "2026-11-25",
    trend: [...data.trend, { ...data.trend[4], tradeDate: "2026-11-26" }],
  }));
  expect(await screen.findByText("华夏沪深300ETF")).toBeInTheDocument();
  expect(screen.getByText("日线收盘")).toHaveTextContent("2026-11-26");
  expect(within(chart).getByText("11-26")).toBeInTheDocument();
  expect(within(chart).getByRole("status")).toHaveTextContent("2026-11-25");
  expect(screen.getByRole("button", { name: "3 个月" })).toHaveAttribute("aria-pressed", "true");
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

it("distinguishes an HTTP 503 from empty data and keeps the table headers in the empty state", async () => {
  const fetchMock = vi.fn().mockResolvedValueOnce(json({ code: "ETF_ACTIVITY_SOURCE_UNAVAILABLE" }, 503)).mockResolvedValueOnce(json({
    tradeDate: null, previousTradeDate: null, oneMonthStartDate: null, trend: [], ranking: { status: "empty", rows: [], error: null },
  }));
  vi.stubGlobal("fetch", fetchMock);
  render(<EtfActivityPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("ETF 动态暂不可读取，请重试");
  expect(screen.queryByText("暂无成交额排行")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(await screen.findByText("暂无成交额排行")).toBeInTheDocument();
  expect(screen.getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(HEADERS);
  expect(screen.getByText("暂无可用的 ETF 日线数据")).toBeInTheDocument();
});

it("times out even after headers arrive, ignores old JSON after retry, and aborts on leaving", async () => {
  vi.useFakeTimers();
  const oldBody = deferred<EtfActivityResponse>();
  const first = { ok: true, status: 200, json: vi.fn(() => oldBody.promise) };
  const fetchMock = vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(json(data));
  vi.stubGlobal("fetch", fetchMock);
  const page = render(<EtfActivityPage />);
  await act(async () => {});
  expect(first.json).toHaveBeenCalledOnce();
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByRole("alert")).toHaveTextContent("ETF 动态请求超时，请重试");
  expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "重试" })); });
  await act(async () => { oldBody.resolve({ ...data, tradeDate: "2026-10-23" }); });
  expect(screen.getByText("日线收盘")).toHaveTextContent("2026-11-25");
  page.unmount();

  const inFlight = deferred<Response>();
  fetchMock.mockImplementationOnce(() => inFlight.promise);
  const reopening = render(<EtfActivityPage />);
  await act(async () => {});
  const signal = fetchMock.mock.calls[2][1].signal;
  expect(signal.aborted).toBe(false);
  reopening.unmount();
  expect(signal.aborted).toBe(true);
  await act(async () => { inFlight.resolve(json(data)); });
  expect(screen.queryByText("日线收盘")).not.toBeInTheDocument();
});
