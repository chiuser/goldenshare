import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import type { MajorEtfMonitorResponse } from "../../features/wealth-exploration/major-etf-monitor/api/majorEtfMonitorApi";
import { EtfActivityPage } from "./EtfActivityPage";

const MARKET_API = "/api/v1/wealth/market/etf-activity";
const MAJOR_API = "/api/v1/wealth/market/major-etf-monitor";
const TREND = "主要ETF（国家队）成交额趋势";
const QUOTES = "主要ETF（国家队）行情";
const HEADERS = ["ETF 代码", "ETF 名称", "现价（元）", "涨跌幅", "成交额（亿元）"];
const CODES = [
  "510300.SH", "510310.SH", "510330.SH", "159919.SZ", "510050.SH", "510500.SH", "512500.SH",
  "512100.SH", "159845.SZ", "560010.SH", "159629.SZ", "159915.SZ", "159977.SZ", "588000.SH",
];
const EMPTY = { status: "empty", tradeDate: null, oneMonthStartDate: null, trend: [], quotes: [] };
// First quote and latest trend point are from the Stage 1 independent DG reconciliation (LLD §7).
// Other chart points and partial quotes exercise calendar bounds, rounded zero and DG's nullable fields.
const READY: MajorEtfMonitorResponse = {
  status: "ready", tradeDate: "2026-11-26", oneMonthStartDate: "2026-10-26",
  trend: [
    { tradeDate: "2026-08-26", amountYuan: 109_000_000_000 },
    { tradeDate: "2026-10-26", amountYuan: 0 },
    { tradeDate: "2026-11-24", amountYuan: null },
    { tradeDate: "2026-11-25", amountYuan: 20_000_000_000 },
    { tradeDate: "2026-11-26", amountYuan: 44_382_245_742.60 },
  ],
  quotes: CODES.map((tsCode, index) => ({
    tsCode,
    name: ["华泰柏瑞沪深300ETF", "易方达沪深300ETF", "华夏沪深300ETF"][index] ?? null,
    closePrice: index === 3 ? null : 3.959,
    priceChangePct: index === 3 ? null : ([-0.28, 1.23, -0.001][index] ?? 0),
    amountYuan: index === 3 ? null : 3_419_450_769,
  })),
};
const MARKET = {
  tradeDate: "2026-11-26", previousTradeDate: "2026-11-25", oneMonthStartDate: "2026-10-26",
  trend: [{ tradeDate: "2026-11-26", amountYuan: 180_000_000_000, ma5Yuan: 175_000_000_000, ma20Yuan: 170_000_000_000 }],
  ranking: { status: "empty", error: null, rows: [] },
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}

function useFetchFixture(majorRequest: (init: RequestInit) => Promise<Response>) {
  const fetchMock = vi.fn((url: string, init: RequestInit) => {
    if (url === MAJOR_API) return majorRequest(init);
    expect(url).toBe(MARKET_API);
    return Promise.resolve(json(MARKET));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function panel(title: string) {
  return within(screen.getByRole("region", { name: title }));
}

function chart() {
  return panel(TREND).getByRole("group", { name: /主要ETF 成交额趋势图/ });
}

function range(name: string) {
  return panel(TREND).getByRole("button", { name });
}

function assertHeaders() {
  expect(panel(QUOTES).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual(HEADERS);
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("renders the five API fields in order and switches only the lower chart without requesting again", async () => {
  const fetchMock = useFetchFixture(async () => json(READY));
  render(<EtfActivityPage />);
  await panel(QUOTES).findByText(CODES[13]);
  assertHeaders();
  const body = panel(QUOTES).getByRole("region", { name: "主要ETF 行情表体" });
  const rows = within(body).getAllByRole("row").slice(1);
  expect(rows.map((row) => within(row).getAllByRole("cell")[0].textContent)).toEqual(CODES);
  expect(within(rows[0]).getAllByRole("cell").map((cell) => cell.textContent)).toEqual([
    "510300.SH", "华泰柏瑞沪深300ETF", "3.959", "−0.28%", "34.19",
  ]);
  expect(within(rows[0]).getByText("−0.28%")).toHaveClass("down");
  expect(within(rows[1]).getByText("+1.23%")).toHaveClass("up");
  expect(within(rows[2]).getByText("0.00%")).toHaveClass("flat");
  expect(within(rows[3]).getAllByText("—")).toHaveLength(4);
  expect(panel(QUOTES).getByText("日线收盘")).toHaveTextContent("2026-11-26");
  expect(panel(QUOTES).getByText("14 只 ETF")).toBeInTheDocument();

  body.scrollTop = 112;
  expect(range("1 个月")).toHaveAttribute("aria-pressed", "true");
  expect(within(chart()).getByText("10-26")).toBeInTheDocument();
  expect(within(chart()).queryByText("08-26")).not.toBeInTheDocument();
  expect(chart().querySelectorAll("path")).toHaveLength(1);
  expect(chart().querySelector("path")).toHaveAttribute("d", expect.stringMatching(/^M56,325 M[\d.]+,[\d.]+ L/));
  expect(chart().querySelector(".etf-chart-zero")).toHaveAttribute("y1", "325");
  fireEvent.keyDown(chart(), { key: "ArrowLeft" });
  expect(within(chart()).getByRole("status")).toHaveTextContent("443.82 亿元");
  fireEvent.click(range("3 个月"));
  expect(within(chart()).getByText("08-26")).toBeInTheDocument();
  expect(within(chart()).getByRole("status")).toHaveTextContent("2026-11-26");
  for (let index = 0; index < 4; index++) fireEvent.keyDown(chart(), { key: "ArrowLeft" });
  expect(within(chart()).getByRole("status")).toHaveTextContent("2026-08-26");
  fireEvent.click(range("1 个月"));
  expect(within(chart()).queryByRole("status")).not.toBeInTheDocument();
  fireEvent.click(range("3 个月"));
  expect(within(chart()).queryByRole("status")).not.toBeInTheDocument();

  expect(panel(QUOTES).getByRole("region", { name: "主要ETF 行情表体" })).toBe(body);
  expect(body.scrollTop).toBe(112);
  expect(panel("ETF 日成交额趋势").getByRole("button", { name: "1 个月" })).toHaveAttribute("aria-pressed", "true");
  expect(fetchMock.mock.calls.map(([url]) => url).sort()).toEqual([MARKET_API, MAJOR_API]);
});

it("preserves zero and null dates without treating an incomplete total as zero", async () => {
  useFetchFixture(async () => json({
    ...READY, quotes: [], trend: READY.trend.slice(1, 3),
  }));
  render(<EtfActivityPage />);
  await screen.findByText("暂无可用的主要ETF行情");
  expect(panel(QUOTES).getByText("日线收盘")).toHaveTextContent("—");
  assertHeaders();
  fireEvent.keyDown(chart(), { key: "ArrowRight" });
  expect(within(chart()).getByRole("status")).toHaveTextContent("2026-11-24");
  expect(within(chart()).getByRole("status")).toHaveTextContent("—");
  fireEvent.keyDown(chart(), { key: "ArrowLeft" });
  expect(within(chart()).getByRole("status")).toHaveTextContent("0.00 亿元");
  expect(chart().querySelector("path")).toHaveAttribute("d", "M56,325");
  expect(chart().querySelector("circle")).toHaveAttribute("cy", "325");
  expect(within(chart()).getByText("4")).toBeInTheDocument();
});

it("allows switching out of an empty month when the three-month window has data", async () => {
  useFetchFixture(async () => json({
    ...READY, trend: [READY.trend[0], { tradeDate: READY.tradeDate, amountYuan: null }],
  }));
  render(<EtfActivityPage />);
  await screen.findByText("暂无可用的主要ETF成交额数据");
  expect(range("3 个月")).toBeEnabled();
  expect(panel(QUOTES).getByText(CODES[13])).toBeInTheDocument();
  fireEvent.click(range("3 个月"));
  expect(within(chart()).getByText("08-26")).toBeInTheDocument();
});

it("keeps the five headings through loading, HTTP failure, retry and empty response", async () => {
  const response = deferred<Response>();
  const retried = deferred<Response>();
  const request = vi.fn().mockReturnValueOnce(response.promise).mockReturnValueOnce(retried.promise);
  const fetchMock = useFetchFixture(request);
  render(<EtfActivityPage />);
  assertHeaders();
  expect(screen.getByText("正在读取主要ETF成交额…")).toBeInTheDocument();
  expect(screen.getByText("正在读取主要ETF行情…")).toBeInTheDocument();
  expect(panel(QUOTES).getByRole("table").querySelectorAll("tbody tr")).toHaveLength(10);
  expect(range("3 个月")).toBeDisabled();
  response.resolve(json({ code: "MAJOR_ETF_MONITOR_SOURCE_UNAVAILABLE" }, 503));
  expect(await panel(QUOTES).findByRole("alert")).toHaveTextContent("主要ETF行情暂不可读取");
  expect(screen.getByText("主要ETF成交额趋势暂不可读取")).toBeInTheDocument();
  expect(panel(QUOTES).getByText("日线收盘")).toHaveTextContent("—");
  assertHeaders();
  const originalChart = panel("ETF 日成交额趋势").getByRole("group");
  fireEvent.keyDown(originalChart, { key: "ArrowLeft" });
  fireEvent.click(screen.getByRole("button", { name: "重试" }));
  expect(screen.getByText("正在读取主要ETF行情…")).toBeInTheDocument();
  retried.resolve(json(EMPTY));
  await panel(QUOTES).findByText("暂无可用的主要ETF行情");
  assertHeaders();
  expect(screen.getByText("暂无可用的主要ETF成交额数据")).toBeInTheDocument();
  expect(range("3 个月")).toBeDisabled();
  expect(within(originalChart).getByRole("status")).toHaveTextContent("1800.00 亿");
  const paths = fetchMock.mock.calls.map(([url]) => url);
  expect(paths.slice(0, 2).sort()).toEqual([MARKET_API, MAJOR_API]);
  expect(paths.slice(2)).toEqual([MAJOR_API]);
});

it("times out JSON reading, ignores a late response after retry and aborts a pending visit on unmount", async () => {
  vi.useFakeTimers();
  const slowBody = deferred<MajorEtfMonitorResponse>();
  const pendingFetch = deferred<Response>();
  const first = { ok: true, status: 200, json: vi.fn(() => slowBody.promise) };
  const request = vi.fn<(init: RequestInit) => Promise<Response>>()
    .mockResolvedValueOnce(first as unknown as Response)
    .mockResolvedValueOnce(json(READY))
    .mockReturnValueOnce(pendingFetch.promise);
  useFetchFixture(request);
  const page = render(<EtfActivityPage />);
  await act(async () => {});
  expect(first.json).toHaveBeenCalledOnce();
  await act(async () => { await vi.advanceTimersByTimeAsync(4999); });
  expect(panel(QUOTES).getByText("正在读取主要ETF行情…")).toBeInTheDocument();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(panel(QUOTES).getByRole("alert")).toHaveTextContent("主要ETF行情请求超时");
  expect(request.mock.calls[0][0].signal?.aborted).toBe(true);
  await act(async () => { fireEvent.click(panel(QUOTES).getByRole("button", { name: "重试" })); });
  await act(async () => { slowBody.resolve({ ...READY, tradeDate: "2026-08-26" }); });
  expect(panel(QUOTES).getByText("日线收盘")).toHaveTextContent("2026-11-26");
  page.unmount();

  const next = render(<EtfActivityPage />);
  await act(async () => {});
  const signal = request.mock.calls[2][0].signal;
  expect(signal?.aborted).toBe(false);
  next.unmount();
  expect(signal?.aborted).toBe(true);
  await act(async () => { pendingFetch.resolve(json(READY)); });
  expect(screen.queryByRole("table", { name: QUOTES })).not.toBeInTheDocument();
});
