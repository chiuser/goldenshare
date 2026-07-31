import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../features/auth/model/AuthProvider";
import { WealthRouter } from "../../app/routes/WealthRouter";
import { StockDetailPage } from "./StockDetailPage";

describe("StockDetailPage", () => {
  function mockStockDetailFetch({ fail = false, supportsMinute = false }: { fail?: boolean; supportsMinute?: boolean } = {}) {
    const pageInit = {
      pageContext: {
        market: "CN_A",
        tradeDate: "2026-05-29",
        prevTradeDate: "2026-05-28",
        isTradingDay: true,
        sessionStatus: "CLOSED",
        timezone: "Asia/Shanghai",
        generatedAt: "2026-05-29T20:00:00+08:00",
        source: "explicit",
      },
      stock: {
        tsCode: "603806.SH",
        symbol: "603806",
        name: "福斯特",
        market: "主板",
        exchange: "SSE",
        industry: "光伏设备",
        area: "浙江",
        listStatus: "L",
        tags: ["光伏设备", "浙江"],
      },
      quote: {
        tradeDate: "2026-05-29",
        price: 19.1,
        change: 0.2,
        changePct: 1.25,
        direction: "UP",
        open: 18.7,
        high: 19.4,
        low: 18.2,
        close: 19.1,
        preClose: 18.9,
        turnoverRate: 1.23,
        volumeRatio: 1.11,
        vol: 123456,
        amount: 2345678,
      },
      chartDefaults: {
        defaultPeriod: "day",
        defaultAdjustment: "forward",
        sourceAdjustment: "qfq",
        availablePeriods: ["day"],
        availableAdjustments: ["forward"],
        availableMainOverlays: ["MA", "BOLL"],
        availableIndicatorTabs: ["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"],
      },
      capabilities: {
        supportsRealtime: false,
        supportsMinute,
        minuteFrequencies: supportsMinute ? [1, 5, 15, 30, 60, 90, 120] : [],
        supportsWeeklyMonthly: false,
        supportsUserActions: false,
        unsupportedActions: ["自选", "提醒", "交易计划", "诊股"],
      },
      dataStatus: {
        status: "READY",
        expectedTradeDate: "2026-05-29",
        observedTradeDate: "2026-05-29",
        note: "ready",
      },
    };
    const kline = {
      pageContext: pageInit.pageContext,
      stockRef: { tsCode: "603806.SH", name: "福斯特" },
      period: "day",
      adjustment: "forward",
      sourceAdjustment: "qfq",
      bars: [
        {
          tradeDate: "2026-05-28",
          open: 18.1,
          high: 18.9,
          low: 17.9,
          close: 18.5,
          preClose: 18.0,
          change: 0.5,
          changePct: 2.7,
          vol: 100000,
          amount: 1800000,
          turnoverRate: 1.1,
          volumeRatio: 1.0,
          factors: {
            ma: { ma5: 18.4, ma10: 18.3, ma20: 18.2, ma30: 18.1, ma60: 18.0, ma90: 17.9, ma250: 17.8 },
            boll: { upper: 19.5, middle: 18.5, lower: 17.5 },
            macd: { dif: 0.1, dea: 0.2, macd: 0.3 },
            kdj: { k: 44.4, d: 55.5, j: 66.6 },
          },
        },
        {
          tradeDate: "2026-05-29",
          open: 18.7,
          high: 19.4,
          low: 18.2,
          close: 19.1,
          preClose: 18.9,
          change: 0.2,
          changePct: 1.25,
          vol: 123456,
          amount: 2345678,
          turnoverRate: 1.23,
          volumeRatio: 1.11,
          factors: {
            ma: { ma5: 19.0, ma10: 18.9, ma20: 18.8, ma30: 18.7, ma60: 18.6, ma90: 18.5, ma250: 18.4 },
            boll: { upper: 20.1, middle: 19.1, lower: 18.1 },
            macd: { dif: 0.11, dea: 0.22, macd: 0.33 },
            kdj: { k: 45.5, d: 56.6, j: 77.7 },
          },
        },
      ],
      meta: { count: 2, limit: 300, endDate: "2026-05-29" },
      dataStatus: pageInit.dataStatus,
    };

    const minuteBars = {
      tsCode: "603806.SH",
      freq: 5,
      bars: [
        {
          tsCode: "603806.SH",
          freq: 5,
          tradeDate: "2026-05-29",
          tradeTime: "2026-05-29T14:55:00+08:00",
          open: 19,
          high: 19.2,
          low: 18.9,
          close: 19.1,
          vol: 1200,
          amount: 22800,
          exchange: "SSE",
        },
      ],
      meta: { count: 1, limit: 500, hasMore: false },
      dataStatus: {
        status: "READY",
        expectedEndDate: "2026-05-29",
        observedEndDate: "2026-05-29",
        message: null,
      },
    };
    const minuteIndicators = {
      tsCode: "603806.SH",
      freq: 5,
      items: [
        {
          tsCode: "603806.SH",
          freq: 5,
          tradeDate: "2026-05-29",
          tradeTime: "2026-05-29T14:55:00+08:00",
          macdDif: null,
          macdDea: null,
          macd: null,
          kdjK: null,
          kdjD: null,
          kdjJ: null,
          paramsKey: "macd_12_26_9__kdj_9_3_3",
          indicatorVersion: 1,
        },
      ],
      meta: { count: 1, limit: 500, hasMore: false },
      dataStatus: minuteBars.dataStatus,
    };

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (fail) return new Response(JSON.stringify({ code: "internal_error", message: "接口失败" }), { status: 500 });
      if (url.includes("/page-init")) return new Response(JSON.stringify(pageInit), { status: 200 });
      if (url.includes("/kline")) return new Response(JSON.stringify(kline), { status: 200 });
      if (supportsMinute && url.includes("/minutes")) return new Response(JSON.stringify(minuteBars), { status: 200 });
      if (supportsMinute && url.includes("/minute-indicators")) return new Response(JSON.stringify(minuteIndicators), { status: 200 });
      return new Response("{}", { status: 404 });
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
  }

  beforeEach(() => {
    mockStockDetailFetch();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.localStorage.clear();
    window.history.replaceState({}, "", "/wealth/market/overview");
  });

  it("renders stock detail route for authenticated users", async () => {
    window.localStorage.setItem("wealth.auth.access-token", "mock-token");
    window.history.replaceState({}, "", "/wealth/market/stock/603806.SH");

    render(
      <AuthProvider>
        <WealthRouter />
      </AuthProvider>,
    );

    expect(screen.getByLabelText("TopMarketBar")).toBeInTheDocument();
    expect(screen.getByLabelText("股票详情加载中")).toBeInTheDocument();
    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    expect(screen.getByLabelText("K线主图")).toBeInTheDocument();
    expect(screen.getByLabelText("右侧信息栏")).toBeInTheDocument();
    expect(screen.getAllByText("MA10:18.90").length).toBeGreaterThan(0);
    expect(screen.queryByText(/MA15/)).not.toBeInTheDocument();
    expect(screen.queryByText(/MA120/)).not.toBeInTheDocument();
  });

  it("supports visible period, overlay, tab and toast interactions", async () => {
    render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "周K" }));
    expect(screen.getByText("周K 首期暂未接入真实数据")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("主图指标切换"), { target: { value: "BOLL" } });
    expect(screen.getByText(/UPPER:/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "资料" }));
    expect(screen.getByText("公司资料、财务摘要与公告入口将在后续真实 API 方案中接入。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "主力密码" }));
    expect(screen.getByText("主力密码 指标暂未支持")).toBeInTheDocument();
  });

  it("loads both minute endpoints with one shared bounded request window", async () => {
    const fetchMock = mockStockDetailFetch({ supportsMinute: true });
    render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "5分" }));

    await waitFor(() => {
      const minuteRequests = fetchMock.mock.calls
        .map(([input]) => String(input))
        .filter((url) => url.includes("/stock-detail/minutes") || url.includes("/stock-detail/minute-indicators"));
      expect(minuteRequests).toHaveLength(2);
    });

    const minuteRequests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes("/stock-detail/minutes") || url.includes("/stock-detail/minute-indicators"));
    expect(minuteRequests[0]).toContain("freq=5");
    expect(minuteRequests[0]).toContain("endDate=2026-05-29");
    expect(minuteRequests[0]).toContain("limit=500");
    expect(minuteRequests[1]).toContain("freq=5");
    expect(minuteRequests.some((url) => url.includes("/stock-detail/minute-indicators"))).toBe(true);
    expect(screen.getByLabelText("分钟图表区")).toBeInTheDocument();
    expect(screen.getByText("分钟K线")).toBeInTheDocument();
  });

  it("shows error state instead of mock quote when real api fails", async () => {
    mockStockDetailFetch({ fail: true });

    render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByLabelText("股票详情加载失败")).toBeInTheDocument();
    expect(screen.getByText("接口失败")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText("K线主图")).not.toBeInTheDocument());
  });
});
