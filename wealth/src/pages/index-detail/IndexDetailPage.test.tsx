import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IndexDetailWeightsResponseDto } from "../../features/index-detail/api/indexDetailApiTypes";
import { makeKline, makePageInit, makeTrendPayload } from "../../features/index-detail/testing/indexDetailTestFixtures";
import * as debugLoader from "../../features/index-detail/debug/useIndexDebugModule";
import * as forecastHook from "../../features/index-detail/xxm-forecast/useXxmForecast";
import type { IndexRecognitionProps, IndexRecognitionDebugExtension, IndexRecognitionDebugModule, IndexRecognitionDebugProps } from "../../features/index-detail/debug/types";
import { IndexDetailPage } from "./IndexDetailPage";

const p4View = vi.hoisted(() => ({ recognition: null as IndexRecognitionProps | null, extension: undefined as IndexRecognitionDebugExtension | undefined }));

vi.mock("../../features/index-detail/chart/IndexChartWorkspace", () => ({
  IndexChartWorkspace: ({ nineTurnLayer, recognition, debugExtension }: { nineTurnLayer: { phase: string }; recognition: IndexRecognitionProps; debugExtension?: IndexRecognitionDebugExtension }) => { p4View.recognition=recognition; p4View.extension=debugExtension; return <div aria-label="指数日线图表区" data-nine-turn-phase={nineTurnLayer.phase} />; },
}));

vi.mock("../../features/index-detail/chart/IndexMinuteChartWorkspace", () => ({
  IndexMinuteChartWorkspace: ({ data, errorMessage, nineTurnLayer, phase }: { data: { freq: number } | null; errorMessage: string; nineTurnLayer: { phase: string }; phase: string }) => (
    <div aria-label="指数分钟图表区" data-freq={data?.freq ?? ""} data-nine-turn-phase={nineTurnLayer.phase} data-phase={phase}>{errorMessage}</div>
  ),
}));

describe("IndexDetailPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/wealth/market/overview");
  });

  it("renders the Loaded skeleton, fixed basic fields, three tabs, and lazily cached full weights", async () => {
    const fetchMock = mockFetch("000001.SH");
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    expect(await screen.findByText("上证指数 000001.SH")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "返回首页" })).toBeInTheDocument();
    expect(screen.getByLabelText("指数日线图表区")).toBeInTheDocument();
    expect(screen.getAllByRole("tab")).toHaveLength(3);
    expect(screen.getAllByText("下跌数")).toHaveLength(1);
    expect(screen.queryByText("成交状态")).not.toBeInTheDocument();
    expect(screen.queryByText("较昨日")).not.toBeInTheDocument();
    expect(screen.queryByText("前复权")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "5分" })).toBeDisabled();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/weights"))).toBe(false);

    fireEvent.click(screen.getByRole("tab", { name: "权重股贡献" }));
    const weightViewport = await screen.findByLabelText("权重股滚动列表");
    expect(weightViewport).toHaveAttribute("data-total-rows", "24");
    fireEvent.scroll(weightViewport, { target: { scrollTop: 320 } });
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/weights"))).toHaveLength(1));
    fireEvent.click(screen.getByRole("tab", { name: "技术面" }));
    expect(screen.getAllByText("--").length).toBeGreaterThanOrEqual(2);
    fireEvent.click(screen.getByRole("tab", { name: "权重股贡献" }));
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/weights"))).toHaveLength(1);
    expect(screen.getByLabelText("权重股滚动列表")).toHaveProperty("scrollTop", 320);
  });

  it("renders weight rows in the contribution order supplied by the API", async () => {
    const pageInit = makePageInit("399001.SZ");
    const weights = makeWeights(pageInit, "READY");
    weights.rows = [
      { ...weights.rows[0], conCode: "600010.SH", name: "正贡献", weight: 1, contributionPoint: 2 },
      { ...weights.rows[1], conCode: "600020.SH", name: "零贡献", weight: 50, contributionPoint: 0 },
      { ...weights.rows[2], conCode: "600030.SH", name: "负贡献", weight: 99, contributionPoint: -1 },
      { ...weights.rows[3], conCode: "600040.SH", name: "贡献缺失", weight: 100, contributionPoint: null, direction: "UNKNOWN" },
    ];
    weights.coverage = {
      totalCount: 4,
      returnedCount: 4,
      contributionAvailableCount: 3,
      contributionMissingCount: 1,
      isTruncated: false,
    };
    mockFetch("399001.SZ", { weights: () => response(weights) });
    render(<IndexDetailPage search="" tsCode="399001.SZ" />);

    await screen.findByText("深证成指 399001.SZ");
    fireEvent.click(screen.getByRole("tab", { name: "权重股贡献" }));
    const viewport = await screen.findByLabelText("权重股滚动列表");
    expect(Array.from(viewport.querySelectorAll(".index-weight-row small"), (node) => node.textContent)).toEqual([
      "600010.SH",
      "600020.SH",
      "600030.SH",
      "600040.SH",
    ]);
  });

  it.each([false, true])("keeps monthly rows without warnings when quotes are missing (all=%s)", async (allMissing) => {
    // LLD §25: four A-share members; three classified or none classified.
    // Use distinct supported indices so earlier tests' real module cache cannot supply their 24-row response.
    const tsCode = allMissing ? "000510.SH" : "000688.SH";
    const pageInit = makePageInit(tsCode);
    pageInit.constituentBreadth = { ...pageInit.constituentBreadth!, totalConstituentCount: 4,
      matchedCount: allMissing ? 0 : 3, missingCount: allMissing ? 4 : 1,
      upCount: allMissing ? 0 : 1, flatCount: allMissing ? 0 : 1, downCount: allMissing ? 0 : 1 };
    const weights = makeWeights(pageInit, "READY");
    weights.rows = [
      { conCode: "600001.SH", name: "上涨样本", weight: 10, changePct: allMissing ? null : 1, contributionPoint: allMissing ? null : 1, direction: allMissing ? "UNKNOWN" : "UP" },
      { conCode: "600003.SH", name: "停牌样本", weight: 30, changePct: allMissing ? null : 0, contributionPoint: allMissing ? null : 0, direction: allMissing ? "UNKNOWN" : "FLAT" },
      { conCode: "600002.SH", name: "下跌样本", weight: 20, changePct: allMissing ? null : -2, contributionPoint: allMissing ? null : -4, direction: allMissing ? "UNKNOWN" : "DOWN" },
      { conCode: "601059.SH", name: "缺行情样本", weight: 40, changePct: null, contributionPoint: null, direction: "UNKNOWN" },
    ];
    weights.coverage = { totalCount: 4, returnedCount: 4, contributionAvailableCount: allMissing ? 0 : 3, contributionMissingCount: allMissing ? 4 : 1, isTruncated: false };
    const fetchMock = mockFetch(tsCode, { pageInit: () => response(pageInit), weights: () => response(weights) });
    render(<IndexDetailPage search="" tsCode={tsCode} />);
    await screen.findByLabelText("指数日线图表区");
    expect(metricValue("upCount")).toBe(allMissing ? "0" : "1");
    expect(metricValue("flatCount")).toBe(allMissing ? "0" : "1");
    expect(metricValue("downCount")).toBe(allMissing ? "0" : "1");
    expect(screen.queryByLabelText("部分数据缺失")).not.toBeInTheDocument();
    expect(screen.queryByText(/部分基本行情|缺少 .* 个成分行情/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "权重股贡献" }));
    const viewport = await screen.findByLabelText("权重股滚动列表");
    expect(viewport).toHaveAttribute("data-total-rows", "4");
    expect(viewport.querySelectorAll(".index-weight-row")).toHaveLength(4);
    expect(viewport.querySelector(".index-weight-row:last-child > span:last-child")).toHaveTextContent("--");
    expect(screen.queryByText("部分贡献点暂不可用，缺失值保留为 --。")).not.toBeInTheDocument();
    expect(screen.queryByText("最新价")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "基本行情" }));
    fireEvent.click(screen.getByRole("tab", { name: "权重股贡献" }));
    expect(screen.getByLabelText("权重股滚动列表")).toHaveAttribute("data-total-rows", "4");
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/weights"))).toHaveLength(1);
    expect(screen.queryByLabelText("部分数据缺失")).not.toBeInTheDocument();
  });

  it("returns a direct index detail visit to the Wealth overview", async () => {
    window.history.replaceState({}, "", "/wealth/market/index/000001.SH");
    mockFetch("000001.SH");
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    expect(await screen.findByText("上证指数 000001.SH")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回首页" }));

    expect(window.location.pathname).toBe("/wealth/market/overview");
  });

  it("switches local minute periods without refreshing daily modules and reuses the period cache", async () => {
    const local = makePageInit("000001.SH");
    local.capabilities.supportsMinute = true;
    local.capabilities.minuteFrequencies = [1, 5, 15, 30, 60, 90, 120];
    local.capabilities.nineTurnPeriods = ["day", "5", "15", "30", "60", "90", "120"];
    local.chartDefaults.availablePeriods = ["day", "m1", "m5", "m15", "m30", "m60", "m90", "m120"];
    const fetchMock = mockFetch("000001.SH", {
      minuteIndicators: (url) => response(makeMinuteIndicatorResponse(Number(url.searchParams.get("freq")))),
      minutes: (url) => response(makeMinuteResponse(Number(url.searchParams.get("freq")))),
      pageInit: () => response(local),
    });
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    expect(await screen.findByLabelText("指数日线图表区")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "5分" }));
    const minuteChart = await screen.findByLabelText("指数分钟图表区");
    await waitFor(() => expect(minuteChart).toHaveAttribute("data-phase", "ready"));
    await waitFor(() => expect(minuteChart).toHaveAttribute("data-nine-turn-phase", "READY"));
    expect(minuteChart).toHaveAttribute("data-freq", "5");
    expect(screen.getByLabelText("IndexHeader")).toHaveTextContent("3940.04");

    fireEvent.click(screen.getByRole("button", { name: "日K" }));
    expect(screen.getByLabelText("指数日线图表区")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "5分" }));
    await waitFor(() => expect(screen.getByLabelText("指数分钟图表区")).toHaveAttribute("data-phase", "ready"));

    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/minutes"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/minute-indicators"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/minute-nine-turn"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/kline"))).toHaveLength(1);
  });

  it("uses the page-init matrix for index nine-turn and keeps 1 minute at zero requests", async () => {
    const local = makePageInit("000001.SH");
    local.capabilities.supportsMinute = true;
    local.capabilities.minuteFrequencies = [1, 5, 15, 30, 60, 90, 120];
    local.capabilities.nineTurnPeriods = ["day", "5", "15", "30", "60", "90", "120"];
    local.chartDefaults.availablePeriods = ["day", "m1", "m5", "m15", "m30", "m60", "m90", "m120"];
    const fetchMock = mockFetch("000001.SH", {
      minuteIndicators: (url) => response(makeMinuteIndicatorResponse(Number(url.searchParams.get("freq")))),
      minutes: (url) => response(makeMinuteResponse(Number(url.searchParams.get("freq")))),
      pageInit: () => response(local),
    });
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    await screen.findByLabelText("指数日线图表区");
    fireEvent.click(screen.getByRole("button", { name: "1分" }));
    await waitFor(() => expect(screen.getByLabelText("指数分钟图表区")).toHaveAttribute("data-phase", "ready"));
    expect(screen.getByLabelText("指数分钟图表区")).toHaveAttribute("data-nine-turn-phase", "UNSUPPORTED");
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/minute-nine-turn"))).toHaveLength(0);

    fireEvent.click(screen.getByRole("tab", { name: "技术面" }));
    const summary = await screen.findByLabelText("九转序列摘要");
    await waitFor(() => expect(summary).toHaveTextContent("上序 3"));
    const rows = Array.from(summary.querySelectorAll(".index-nine-turn-summary-row"));
    expect(rows.map((row) => row.firstElementChild?.textContent)).toEqual(["日线", "15分钟", "30分钟", "60分钟", "90分钟", "120分钟"]);
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/minute-nine-turn"))).toHaveLength(5));
    const requestedSummaryFrequencies = fetchMock.mock.calls
      .filter(([input]) => String(input).includes("/minute-nine-turn"))
      .map(([input]) => new URL(String(input)).searchParams.get("freq"));
    expect(requestedSummaryFrequencies.sort()).toEqual(["120", "15", "30", "60", "90"]);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/nine-turn"))).toHaveLength(1);
  });

  it("keeps the index chart when nine-turn fails and retries only the failed layer", async () => {
    let nineTurnCalls = 0;
    const fetchMock = mockFetch("000001.SH", {
      nineTurn: () => ++nineTurnCalls === 1
        ? response({ code: "NT_QUERY_FAILED", message: "九转服务失败" }, 500)
        : response(makeIndexNineTurnResponse("000001.SH", "day")),
    });
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    const chart = await screen.findByLabelText("指数日线图表区");
    await waitFor(() => expect(chart).toHaveAttribute("data-nine-turn-phase", "ERROR"));
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/kline"))).toHaveLength(1);
    fireEvent.click(screen.getByRole("tab", { name: "技术面" }));
    fireEvent.click(await screen.findByRole("button", { name: "重试日线九转" }));
    await waitFor(() => expect(screen.getByLabelText("九转序列摘要")).toHaveTextContent("上序 3"));
    expect(screen.getByLabelText("九转序列摘要").querySelectorAll(".index-nine-turn-summary-row")).toHaveLength(6);
    expect(screen.getByLabelText("指数日线图表区")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/minute-nine-turn"))).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/nine-turn"))).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/kline"))).toHaveLength(1);
  });

  it("keeps North Exchange 50 minute data and nine-turn as local source-empty states", async () => {
    const local = makePageInit("899050.BJ");
    local.capabilities.supportsMinute = true;
    local.capabilities.minuteFrequencies = [1, 5, 15, 30, 60, 90, 120];
    local.capabilities.nineTurnPeriods = ["day", "5", "15", "30", "60", "90", "120"];
    local.chartDefaults.availablePeriods = ["day", "m1", "m5", "m15", "m30", "m60", "m90", "m120"];
    mockFetch("899050.BJ", {
      minuteNineTurn: (url) => response(makeEmptyIndexNineTurnResponse("899050.BJ", url.searchParams.get("freq") as "5" | "15" | "30" | "60" | "90" | "120")),
      minutes: (url) => response(makeEmptyMinuteResponse(Number(url.searchParams.get("freq")), "899050.BJ")),
      pageInit: () => response(local),
    });
    render(<IndexDetailPage search="" tsCode="899050.BJ" />);

    await screen.findByLabelText("指数日线图表区");
    fireEvent.click(screen.getByRole("button", { name: "60分" }));
    const chart = await screen.findByLabelText("指数分钟图表区");
    await waitFor(() => expect(chart).toHaveAttribute("data-phase", "empty"));
    await waitFor(() => expect(chart).toHaveAttribute("data-nine-turn-phase", "SOURCE_EMPTY"));
  });

  it.each(["399001.SZ", "399006.SZ", "000688.SH", "000300.SH", "000905.SH", "000852.SH", "899050.BJ", "000510.SH", "000016.SH"])(
    "never requests the SSE-only trend endpoint for %s",
    async (tsCode) => {
    const fetchMock = mockFetch(tsCode);
    render(<IndexDetailPage search="" tsCode={tsCode} />);
    expect(await screen.findByText(`深证成指 ${tsCode}`)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/trend-channel"))).toBe(false);
    fireEvent.click(screen.getByRole("tab", { name: "技术面" }));
    expect(screen.getByText("当前指数不支持")).toBeInTheDocument();
    },
  );

  it("renders the Figma loading skeleton without stale detail values", () => {
    let resolvePageInit: ((value: Response) => void) | undefined;
    mockFetch("000001.SH", { pageInit: () => new Promise((resolve) => { resolvePageInit = resolve; }) });
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    expect(screen.getByLabelText("正在加载指数行情")).toBeInTheDocument();
    expect(screen.getByText("正在读取日线、技术指标与趋势通道")).toBeInTheDocument();
    expect(screen.queryByText("3940.04")).not.toBeInTheDocument();
    act(() => resolvePageInit?.(response(makePageInit())));
  });

  it("renders Empty with the stable shell, exactly fifteen placeholder metrics, and no downstream request", async () => {
    const replaceState = vi.spyOn(window.history, "replaceState");
    const empty = makePageInit();
    empty.asOfTradeDate = null;
    empty.quote = null;
    empty.dailyBasic = null;
    empty.constituentBreadth = null;
    empty.dataStatus = { status: "EMPTY", expectedTradeDate: "2026-07-31", observedTradeDate: null };
    const fetchMock = mockFetch("000001.SH", { pageInit: () => response(empty) });
    render(<IndexDetailPage search="?tradeDate=2026-07-31" tsCode="000001.SH" />);

    expect(await screen.findByText("暂无指数日线数据")).toBeInTheDocument();
    expect(screen.getByText("上证指数 000001.SH")).toBeInTheDocument();
    expect(document.querySelectorAll("[data-metric-key]")).toHaveLength(15);
    expect([...document.querySelectorAll("[data-metric-key] b")].every((node) => node.textContent === "--")).toBe(true);
    expect(screen.getByText("暂无数据")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/kline"))).toBe(false);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/trend-channel"))).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "查看最近交易日" }));
    expect(replaceState).toHaveBeenCalledWith(expect.any(Object), "", "/wealth/market/index/000001.SH");
    replaceState.mockRestore();
  });

  it("maps 500 to the full-width Error panel and retries the whole page", async () => {
    const fetchMock = mockFetch("000001.SH", {
      pageInit: () => response({ code: "ID_QUERY_FAILED", message: "数据库暂时不可用" }, 500),
    });
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    expect(await screen.findByText("指数详情加载失败")).toBeInTheDocument();
    expect(screen.getByText("ERROR · 请求未完成")).toBeInTheDocument();
    expect(screen.getByLabelText("MainContent")).toHaveClass("full");
    fireEvent.click(screen.getByRole("button", { name: "重新加载" }));
    await waitFor(() => expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/page-init"))).toHaveLength(2));
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/kline"))).toBe(false);
  });

  it("maps 403 to Forbidden and stops kline, trend, and weights requests", async () => {
    const fetchMock = mockFetch("000001.SH", {
      pageInit: () => response({ code: "HTTP_403", message: "Forbidden" }, 403),
    });
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    expect(await screen.findByText("暂无访问权限")).toBeInTheDocument();
    expect(screen.getByText("403 · FORBIDDEN")).toBeInTheDocument();
    expect(screen.getByLabelText("MainContent")).toHaveClass("full");
    expect(fetchMock.mock.calls.some(([input]) => /\/index-detail\/(kline|weights)/.test(String(input)))).toBe(false);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/trend-channel"))).toBe(false);
  });

  it("maps ID_NOT_FOUND to the 404 shell and stops downstream requests", async () => {
    const fetchMock = mockFetch("999999.SH", {
      pageInit: () => response({ code: "ID_NOT_FOUND", message: "指数不在正式名单" }, 404),
    });
    render(<IndexDetailPage search="" tsCode="999999.SH" />);

    expect(await screen.findByText("指数不存在")).toBeInTheDocument();
    expect(screen.getByText("404 · NOT FOUND")).toBeInTheDocument();
    expect(screen.getByText("指数详情 999999.SH")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => /\/index-detail\/(kline|weights)/.test(String(input)))).toBe(false);
  });

  it("maps ID_REQUEST_INVALID to the request-error shell", async () => {
    const fetchMock = mockFetch("000001.SH", {
      pageInit: () => response({ code: "ID_REQUEST_INVALID", message: "tradeDate 无效" }, 400),
    });
    render(<IndexDetailPage search="?tradeDate=invalid" tsCode="000001.SH" />);

    expect(await screen.findByText("指数请求无效")).toBeInTheDocument();
    expect(screen.getByText("400 · INVALID REQUEST")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => /\/index-detail\/(kline|weights)/.test(String(input)))).toBe(false);
  });

  it("keeps Loaded data for Partial and derives the warning from the actual missing fields", async () => {
    const partial = makePageInit("399001.SZ");
    partial.quote = { ...partial.quote!, amount: null };
    partial.dailyBasic = { ...partial.dailyBasic!, peTtm: null };
    partial.constituentBreadth = { ...partial.constituentBreadth!, upCount: 1704, missingCount: 7, matchedCount: 2345 };
    partial.dataStatus = { status: "PARTIAL", expectedTradeDate: "2026-07-31", observedTradeDate: "2026-07-31" };
    mockFetch("399001.SZ", { pageInit: () => response(partial) });
    render(<IndexDetailPage search="" tsCode="399001.SZ" />);

    expect(await screen.findByLabelText("指数日线图表区")).toBeInTheDocument();
    expect(metricValue("amount")).toBe("--");
    expect(metricValue("peTtm")).toBe("--");
    expect(metricValue("preClose")).not.toBe("--");
    const notice = screen.getByLabelText("部分数据缺失");
    expect(notice).toHaveTextContent("金额");
    expect(notice).toHaveTextContent("TTM 市盈率");
    expect(notice).not.toHaveTextContent("成分涨跌统计");
  });

  it("generates a different Partial warning when a different field is missing", async () => {
    const partial = makePageInit("000300.SH");
    partial.dailyBasic = { ...partial.dailyBasic!, pb: null };
    partial.dataStatus = { status: "PARTIAL", expectedTradeDate: "2026-07-31", observedTradeDate: "2026-07-31" };
    mockFetch("000300.SH", { pageInit: () => response(partial) });
    render(<IndexDetailPage search="" tsCode="000300.SH" />);

    const notice = await screen.findByLabelText("部分数据缺失");
    expect(notice).toHaveTextContent("市净率");
    expect(notice).not.toHaveTextContent("金额、TTM 市盈率、平盘数");
    expect(metricValue("pb")).toBe("--");
  });

  it("renders Delayed with the observed and expected dates while preserving the chart", async () => {
    const delayed = makePageInit("399006.SZ");
    delayed.dataStatus = { status: "DELAYED", expectedTradeDate: "2026-08-03", observedTradeDate: "2026-07-31" };
    mockFetch("399006.SZ", { pageInit: () => response(delayed) });
    render(<IndexDetailPage search="" tsCode="399006.SZ" />);

    expect(await screen.findByLabelText("指数日线图表区")).toBeInTheDocument();
    expect(screen.getByLabelText("数据更新延迟")).toHaveTextContent("数据更新至 2026-07-31，预期交易日为 2026-08-03");
    expect(screen.queryByLabelText("部分数据缺失")).not.toBeInTheDocument();
  });

  it("promotes a trend failure to Partial, keeps the chart, and supports trend-only retry", async () => {
    let trendCalls = 0;
    const fetchMock = mockFetch("000001.SH", {
      trend: () => {
        trendCalls += 1;
        return trendCalls === 1
          ? response({ code: "ID_QUERY_FAILED", message: "趋势服务失败" }, 500)
          : response(makeTrendPayload());
      },
    });
    render(<IndexDetailPage search="" tsCode="000001.SH" />);

    expect(await screen.findByLabelText("部分数据缺失")).toHaveTextContent("趋势通道");
    expect(screen.getByLabelText("指数日线图表区")).toBeInTheDocument();
    expect(metricValue("preClose")).not.toBe("--");
    fireEvent.click(screen.getByRole("tab", { name: "技术面" }));
    expect(await screen.findByText("趋势通道加载失败")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.queryByText("趋势通道加载失败")).not.toBeInTheDocument());
    expect(screen.getByText("短期上轨")).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/trend-channel"))).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/kline"))).toHaveLength(1);
  });

  it("keeps the missing index pre-close warning and retries only the weights module", async () => {
    let weightCalls = 0;
    const pageInit = makePageInit("000905.SH");
    pageInit.quote = { ...pageInit.quote!, preClose: null };
    const partialWeights = makeWeights(pageInit, "PARTIAL");
    partialWeights.rows = partialWeights.rows.map(row => ({ ...row, contributionPoint: null }));
    partialWeights.coverage = { ...partialWeights.coverage, contributionAvailableCount: 0, contributionMissingCount: 24 };
    const readyWeights = makeWeights(pageInit, "READY");
    const fetchMock = mockFetch("000905.SH", {
      weights: () => response(++weightCalls === 1 ? partialWeights : readyWeights),
    });
    render(<IndexDetailPage search="" tsCode="000905.SH" />);

    await screen.findByText("深证成指 000905.SH");
    fireEvent.click(screen.getByRole("tab", { name: "权重股贡献" }));
    expect(await screen.findByText("部分贡献点暂不可用，缺失值保留为 --。")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(screen.queryByText("部分贡献点暂不可用，缺失值保留为 --。")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/weights"))).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/kline"))).toHaveLength(1);
  });

  it("does not let a stale page-init response overwrite a newly selected index", async () => {
    let resolveFirst: ((value: Response) => void) | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/major-indices")) return response(makeMajorIndices("399001.SZ", makePageInit("399001.SZ")));
      if (url.includes("tsCode=000001.SH") && url.includes("/page-init")) return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      if (url.includes("tsCode=399001.SZ") && url.includes("/page-init")) return response(makePageInit("399001.SZ"));
      if (url.includes("tsCode=399001.SZ") && url.includes("/kline")) return response(makeKline("399001.SZ"));
      return response({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(<IndexDetailPage search="" tsCode="000001.SH" />);
    rerender(<IndexDetailPage search="" tsCode="399001.SZ" />);

    expect(await screen.findByText("深证成指 399001.SZ")).toBeInTheDocument();
    await act(async () => { resolveFirst?.(response(makePageInit("000001.SH"))); });
    expect(screen.queryByText("上证指数 000001.SH")).not.toBeInTheDocument();
    expect(screen.getByText("深证成指 399001.SZ")).toBeInTheDocument();
  });

  it("removes the loaded index immediately while the next index request is pending", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/major-indices")) return response(makeMajorIndices("000001.SH", makePageInit("000001.SH")));
      if (url.includes("tsCode=000001.SH") && url.includes("/page-init")) return response(makePageInit("000001.SH"));
      if (url.includes("tsCode=000001.SH") && url.includes("/kline")) return response(makeKline("000001.SH"));
      if (url.includes("tsCode=399001.SZ") && url.includes("/page-init")) return new Promise<Response>(() => undefined);
      if (url.includes("/trend-channel")) return response(makeTrendPayload());
      return response({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const { rerender } = render(<IndexDetailPage search="" tsCode="000001.SH" />);
    expect(await screen.findByLabelText("IndexHeader")).toHaveTextContent("3940.04");

    rerender(<IndexDetailPage search="" tsCode="399001.SZ" />);
    expect(screen.getByLabelText("正在加载指数行情")).toBeInTheDocument();
    expect(screen.queryByLabelText("IndexHeader")).not.toBeInTheDocument();
  });
});

interface MockFetchOptions {
  minuteNineTurn?: (url: URL) => Response | Promise<Response>;
  nineTurn?: (url: URL) => Response | Promise<Response>;
  kline?: () => Response | Promise<Response>;
  minuteIndicators?: (url: URL) => Response | Promise<Response>;
  minutes?: (url: URL) => Response | Promise<Response>;
  pageInit?: () => Response | Promise<Response>;
  trend?: () => Response | Promise<Response>;
  weights?: () => Response | Promise<Response>;
}

function mockFetch(tsCode: string, options: MockFetchOptions = {}) {
  const pageInit = makePageInit(tsCode);
  const kline = makeKline(tsCode);
  const weights = makeWeights(pageInit, "READY");
  const majorIndices = makeMajorIndices(tsCode, pageInit);
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/major-indices")) return response(majorIndices);
    if (url.includes("/index-detail/page-init")) return options.pageInit?.() ?? response(pageInit);
    if (url.includes("/index-detail/kline")) return options.kline?.() ?? response(kline);
    if (url.includes("/index-detail/minute-indicators")) return options.minuteIndicators?.(new URL(url)) ?? response({}, 404);
    if (url.includes("/index-detail/minutes")) return options.minutes?.(new URL(url)) ?? response({}, 404);
    if (url.includes("/index-detail/minute-nine-turn")) {
      const parsed = new URL(url);
      return options.minuteNineTurn?.(parsed) ?? response(makeIndexNineTurnResponse(tsCode, parsed.searchParams.get("freq") as "5" | "15" | "30" | "60" | "90" | "120"));
    }
    if (url.includes("/index-detail/nine-turn")) return options.nineTurn?.(new URL(url)) ?? response(makeIndexNineTurnResponse(tsCode, "day"));
    if (url.includes("/index-detail/weights")) return options.weights?.() ?? response(weights);
    if (url.includes("/trend-channel")) return options.trend?.() ?? response(makeTrendPayload());
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function makeIndexNineTurnResponse(tsCode: string, period: "day" | "5" | "15" | "30" | "60" | "90" | "120") {
  const tradeTime = period === "day" ? null : "2026-07-31T09:49:00+08:00";
  const marker = { completed: false, direction: "UP" as const, sequenceNumber: 3 as const, tradeDate: "2026-07-31", tradeTime };
  return {
    dataStatus: { code: null, expectedEndDate: "2026-07-31", message: null, observedEndDate: "2026-07-31", status: "READY" as const },
    debugInfo: null,
    latestMarker: marker,
    markers: [marker],
    meta: { comparisonLag: 4 as const, endDate: "2026-07-31", formulaVersion: 1 as const, hasMore: false, limit: period === "day" ? 300 : 500, markerCount: 1, matchedRowCount: 1, missingRowCount: 0, nextCursor: null, observedEndDate: "2026-07-31", observedStartDate: "2026-07-31", signalThreshold: 9 as const, sourceRowCount: 1, startDate: null },
    period,
    subjectType: "index" as const,
    tsCode,
  };
}

function makeEmptyIndexNineTurnResponse(tsCode: string, period: "5" | "15" | "30" | "60" | "90" | "120") {
  return {
    dataStatus: { code: "NT_SOURCE_NOT_READY", expectedEndDate: "2026-07-31", message: "当前数据源不覆盖该指数分钟九转。", observedEndDate: null, status: "EMPTY" as const },
    debugInfo: null,
    latestMarker: null,
    markers: [],
    meta: { comparisonLag: 4 as const, endDate: "2026-07-31", formulaVersion: 1 as const, hasMore: false, limit: 500, markerCount: 0, matchedRowCount: 0, missingRowCount: 0, nextCursor: null, observedEndDate: null, observedStartDate: null, signalThreshold: 9 as const, sourceRowCount: 0, startDate: null },
    period,
    subjectType: "index" as const,
    tsCode,
  };
}

function makeMinuteResponse(freq: number, tsCode = "000001.SH") {
  return {
    tsCode,
    freq,
    bars: Array.from({ length: 20 }, (_, index) => ({
      tsCode, freq, tradeDate: "2026-07-31",
      tradeTime: `2026-07-31T09:${String(30 + index).padStart(2, "0")}:00+08:00`,
      open: 10 + index, high: 11 + index, low: 9 + index, close: 10.5 + index,
      vol: 100 + index, amount: 1000 + index, exchange: "SSE",
    })).reverse(),
    meta: { count: 20, limit: 500, hasMore: false, nextCursor: null, startDate: null, endDate: "2026-07-31", observedStartDate: "2026-07-31", observedEndDate: "2026-07-31" },
    dataStatus: { status: "READY", code: null, expectedEndDate: "2026-07-31", observedEndDate: "2026-07-31", message: null },
  };
}

function makeEmptyMinuteResponse(freq: number, tsCode: string) {
  return {
    tsCode,
    freq,
    bars: [],
    meta: { count: 0, limit: 500, hasMore: false, nextCursor: null, startDate: null, endDate: "2026-07-31", observedStartDate: null, observedEndDate: null },
    dataStatus: { status: "EMPTY" as const, code: "IM_SOURCE_NOT_READY", expectedEndDate: "2026-07-31", observedEndDate: null, message: "当前数据源不覆盖北证50分钟数据。" },
  };
}

function makeMinuteIndicatorResponse(freq: number, tsCode = "000001.SH") {
  const bars = makeMinuteResponse(freq, tsCode);
  return {
    tsCode: bars.tsCode,
    freq,
    items: bars.bars.map((bar, index) => ({
      tsCode: bar.tsCode, freq, tradeDate: bar.tradeDate, tradeTime: bar.tradeTime,
      ma5: 10 + index, ma10: null, ma20: null, ma30: null, ma60: null, ma90: null, ma250: null,
      bollMiddle: null, bollUpper: null, bollLower: null,
      macdDif: .1, macdDea: .05, macd: .1, kdjK: 50, kdjD: 45, kdjJ: 60,
      observationCount: index + 1,
      paramsKey: "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3",
      indicatorVersion: 1,
    })),
    meta: bars.meta,
    dataStatus: bars.dataStatus,
  };
}

function makeWeights(pageInit: ReturnType<typeof makePageInit>, status: "READY" | "PARTIAL"): IndexDetailWeightsResponseDto {
  return {
    indexRef: { tsCode: pageInit.index.tsCode, name: pageInit.index.name }, contributionTradeDate: "2026-07-31", weightTradeDate: "2026-07-31", isEstimated: true as const,
    rows: Array.from({ length: 24 }, (_, index) => ({ conCode: `600${String(index).padStart(3, "0")}.SH`, name: `成分股${index + 1}`, weight: 5 - index * .1, changePct: 1, contributionPoint: status === "PARTIAL" && index === 23 ? null : .12 - index * .01, direction: (index % 2 === 0 ? "UP" : "DOWN") as "UP" | "DOWN" })),
    coverage: { totalCount: 24, returnedCount: 24, contributionAvailableCount: status === "READY" ? 24 : 23, contributionMissingCount: status === "READY" ? 0 : 1, isTruncated: false as const },
    dataStatus: { status, expectedTradeDate: "2026-07-31", observedTradeDate: "2026-07-31" },
    note: "基于最新月度权重估算，非指数公司官方归因" as const,
    debugInfo: null,
  };
}

function makeMajorIndices(tsCode: string, pageInit: ReturnType<typeof makePageInit>) {
  return { pageStatus: { status: "READY", displayText: "已就绪" }, majorIndices: { definition: { definitionKey: "major", version: "1", fixedCount: 10 }, rows: [{ subject: { subjectType: "index", subjectCode: tsCode, subjectName: pageInit.index.name }, point: 3940.04, changePct: 1.02, direction: "UP" }] }, tradingDay: pageInit.pageContext };
}

function metricValue(key: string): string | null | undefined {
  return document.querySelector(`[data-metric-key="${key}"] b`)?.textContent;
}

function response(payload: unknown, status = 200) { return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } }); }


describe("P4 page uses one effective mode and matching debug owner",()=>{
  afterEach(()=>{vi.restoreAllMocks();vi.unstubAllEnvs();vi.unstubAllGlobals();});
  function setup(){
    let props: IndexRecognitionDebugProps | null=null;
    const module: IndexRecognitionDebugModule={IndexRecognitionDebug:p=>{props=p;return null;},
      decodeXxmDebug:vi.fn(),decodeForecastDebug:vi.fn(),renderXxmDetails:()=>null,renderForecastDetails:()=>null};
    const state:{phase:"idle"|"loading"|"ready"|"error";module:IndexRecognitionDebugModule|null;errorMessage:string;retry:()=>void}=
      {phase:"loading",module:null,errorMessage:"",retry:vi.fn()};
    const loader=vi.spyOn(debugLoader,"useIndexDebugModule").mockImplementation(()=>state);
    const forecast=vi.spyOn(forecastHook,"useXxmForecast").mockReturnValue({rows:{day:{phase:"idle",response:null,error:""},m30:{phase:"unsupported",response:null,error:""},m60:{phase:"unsupported",response:null,error:""},m90:{phase:"unsupported",response:null,error:""},m120:{phase:"unsupported",response:null,error:""}},retry:vi.fn()});
    return {state,module,loader,forecast,props:()=>props};
  }
  it("keeps ordinary requests during loading/error, switches only ready, and immediately clears on exit",async()=>{
    const h=setup();const fetcher=mockFetch("000001.SH");
    const {rerender}=render(<IndexDetailPage tsCode="000001.SH" search="?debug=1"/>);
    await screen.findByLabelText("指数日线图表区");
    expect(p4View.recognition?.debug).toBe(0);expect(h.forecast.mock.lastCall?.[0].debug).toBe(0);
    expect(screen.getByText("核验工具加载中")).toBeInTheDocument();
    const graph=screen.getByLabelText("指数日线图表区");
    h.state.phase="error";h.state.errorMessage="核验工具加载失败";
    rerender(<IndexDetailPage tsCode="000001.SH" search="?debug=1"/>);
    expect(p4View.recognition?.debug).toBe(0);fireEvent.click(screen.getByRole("button",{name:"重试"}));
    expect(h.state.retry).toHaveBeenCalledTimes(1);
    h.state.phase="ready";h.state.module=h.module;
    rerender(<IndexDetailPage tsCode="000001.SH" search="?debug=1"/>);
    expect(p4View.recognition).toMatchObject({debug:1,decodeXxmDebug:h.module.decodeXxmDebug,renderXxmDetails:h.module.renderXxmDetails});
    expect(h.forecast.mock.lastCall?.[0]).toMatchObject({debug:1,decodeDebug:h.module.decodeForecastDebug});
    expect(screen.getByLabelText("指数日线图表区")).toBe(graph);
    const owner=h.props()!;const extension:IndexRecognitionDebugExtension={ownerKey:owner.ownerKey,reviewPhase:"closed",chartOverride:null,controls:null,legend:null,renderWaveDetails:()=>null};
    act(()=>owner.onChange(owner.ownerKey,extension));expect(p4View.extension).toBe(extension);
    act(()=>owner.onChange("old-owner",null));expect(p4View.extension).toBe(extension);
    fireEvent.click(screen.getByRole("tab",{name:"技术面"}));
    rerender(<IndexDetailPage tsCode="000001.SH" search=""/>);
    expect(screen.getByLabelText("正在加载指数行情")).toBeInTheDocument();
    expect(screen.queryByLabelText("指数日线图表区")).not.toBeInTheDocument();
    expect(h.forecast.mock.lastCall?.[0]).toMatchObject({debug:0,active:false});
    act(()=>owner.onChange(owner.ownerKey,extension));
    const reloaded=await screen.findByLabelText("指数日线图表区");
    expect(reloaded).not.toBe(graph);
    expect(p4View.recognition?.debug).toBe(0);expect(p4View.extension).toBeUndefined();
    expect(screen.getByRole("tab",{name:"基本行情"})).toHaveAttribute("aria-selected","true");
    expect(h.loader.mock.lastCall?.[0]).toBe(false);
    for(const endpoint of ["/page-init","/kline","/trend-channel"])
      expect(fetcher.mock.calls.filter(([url])=>String(url).includes(endpoint))).toHaveLength(2);
    const klines=fetcher.mock.calls.map(([url])=>new URL(String(url))).filter(url=>url.pathname.endsWith("/kline"));
    expect(klines.map(url=>url.searchParams.get("debug"))).toEqual(["1",null]);
    expect(fetcher.mock.calls.some(([url])=>String(url).includes("daily-waves"))).toBe(false);
  });
  it.each(["production","north-index"])("keeps all recognition/debug disabled for %s even when loader returns a module",async mode=>{
    const h=setup();h.state.phase="ready";h.state.module=h.module;
    if(mode==="production")vi.stubEnv("DEV",false);
    const code=mode==="production"?"000001.SH":"899050.BJ";
    mockFetch(code);render(<IndexDetailPage tsCode={code} search="?debug=1"/>);
    await screen.findByLabelText("指数日线图表区");
    expect(h.loader.mock.lastCall?.[0]).toBe(false);expect(p4View.recognition).toMatchObject({recognitionEnabled:false,debug:0});
    expect(h.forecast.mock.lastCall?.[0]).toMatchObject({enabled:false,active:false,debug:0});
    expect(h.props()).toBeNull();
  });
  it.each(["000001.SH","399001.SZ","399006.SZ","000688.SH","000300.SH","000905.SH","000852.SH","000510.SH","000016.SH"])("enables recognition and lazy forecast for validated %s",async code=>{
    const h=setup();h.state.phase="ready";h.state.module=h.module;
    const fetcher=mockFetch(code);render(<IndexDetailPage tsCode={code} search="?debug=1"/>);
    await screen.findByLabelText("指数日线图表区");
    expect(h.loader.mock.lastCall?.[0]).toBe(true);
    expect(p4View.recognition).toMatchObject({recognitionEnabled:true,debug:1});
    expect(h.forecast.mock.lastCall?.[0]).toMatchObject({tsCode:code,enabled:true,active:false,minutes:false,debug:1});
    fireEvent.click(screen.getByRole("tab",{name:"技术面"}));
    expect(h.forecast.mock.lastCall?.[0]).toMatchObject({tsCode:code,enabled:true,active:true});
    expect(fetcher.mock.calls.some(([url])=>String(url).includes("daily-waves"))).toBe(false);
  });
  it("does not enable recognition or import debug while page identity is pending",async()=>{
    const h=setup();let finish!: (value:Response)=>void;
    mockFetch("399001.SZ",{pageInit:()=>new Promise<Response>(resolve=>{finish=resolve;})});
    render(<IndexDetailPage tsCode="399001.SZ" search="?debug=1"/>);
    await screen.findByLabelText("正在加载指数行情");
    expect(h.loader.mock.lastCall?.[0]).toBe(false);
    expect(h.forecast.mock.lastCall?.[0]).toMatchObject({enabled:false,active:false});
    await act(async()=>finish(response(makePageInit("399001.SZ"))));
    await screen.findByLabelText("指数日线图表区");
    expect(h.forecast.mock.lastCall?.[0]).toMatchObject({tsCode:"399001.SZ",enabled:true,active:false});
  });
  it.each([
    {stage:"page-init",responseCode:"399001.SZ",title:"暂无指数日线数据"},
    {stage:"page-init",responseCode:"000001.SH",title:"指数详情加载失败"},
    {stage:"kline",responseCode:"399001.SZ",title:"暂无指数日线数据"},
    {stage:"kline",responseCode:"000001.SH",title:"指数详情加载失败"},
  ])("keeps recognition disabled for $stage EMPTY with response code $responseCode",async({stage,responseCode,title})=>{
    // Page wiring only: the real controller consumes API-shaped responses;
    // setup replaces the forecast hook/debug loader and charts are mocked above.
    const h=setup();h.state.phase="ready";h.state.module=h.module;
    const emptyStatus={status:"EMPTY" as const,expectedTradeDate:"2026-07-31",observedTradeDate:null};
    const pageInit=makePageInit(stage==="page-init"?responseCode:"399001.SZ");
    // index_detail_page_query_service.py:73-109 retains identity with null data.
    if(stage==="page-init"){
      pageInit.asOfTradeDate=null;pageInit.quote=null;
      pageInit.dailyBasic=null;pageInit.constituentBreadth=null;pageInit.dataStatus=emptyStatus;
    }
    // index_detail_kline_query_service.py:99-133 retains indexRef with no bars.
    const kline=makeKline(responseCode);kline.bars=[];
    kline.meta={count:0,limit:1000,startDate:null,endDate:"2026-07-31"};kline.dataStatus=emptyStatus;
    const fetcher=mockFetch("399001.SZ",{pageInit:()=>response(pageInit),kline:()=>response(kline)});
    render(<IndexDetailPage tsCode="399001.SZ" search="?debug=1"/>);
    await screen.findByText(title);
    expect(h.loader.mock.lastCall?.[0]).toBe(false);
    expect(h.loader.mock.calls.some(([enabled])=>enabled)).toBe(false);
    expect(h.forecast.mock.lastCall?.[0]).toMatchObject({tsCode:"399001.SZ",enabled:false,active:false,debug:0});
    expect(h.props()).toBeNull();
    expect(screen.queryByLabelText("指数日线图表区")).not.toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([url])=>String(url).includes("/kline"))).toHaveLength(stage==="kline"?1:0);
    expect(fetcher.mock.calls.some(([url])=>String(url).includes("xxm-"))).toBe(false);
  });
  it.each([false,true])("keeps forecast eligibility when the main chart changes to m5 and m90, debug=%s",async debug=>{
    const h=setup();
    if(debug){h.state.phase="ready";h.state.module=h.module;}
    const local=makePageInit("000001.SH");
    local.capabilities.supportsMinute=true;
    local.capabilities.minuteFrequencies=[5,90];
    local.capabilities.nineTurnPeriods=["day","5","90"];
    local.chartDefaults.availablePeriods=["day","m5","m90"];
    mockFetch("000001.SH",{pageInit:()=>response(local),
      minutes:url=>response(makeMinuteResponse(Number(url.searchParams.get("freq")))),
      minuteIndicators:url=>response(makeMinuteIndicatorResponse(Number(url.searchParams.get("freq"))))});
    render(<IndexDetailPage tsCode="000001.SH" search={debug?"?debug=1":""}/>);
    await screen.findByLabelText("指数日线图表区");
    fireEvent.click(screen.getByRole("tab",{name:"技术面"}));
    for(const label of ["5分","90分"]){
      fireEvent.click(screen.getByRole("button",{name:label}));
      await waitFor(()=>expect(screen.getByLabelText("指数分钟图表区")).toHaveAttribute("data-phase","ready"));
      expect(h.forecast.mock.lastCall?.[0]).toMatchObject({active:true,enabled:true,minutes:true,debug:debug?1:0});
    }
  });
});
