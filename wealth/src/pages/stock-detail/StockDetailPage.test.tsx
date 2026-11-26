import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider } from "../../features/auth/model/AuthProvider";
import type { MarketMajorIndicesResponse } from "../../features/major-indices/api/marketMajorIndicesApi";
import { deferred, item, page, rules } from "../../features/watchlist/test/watchlistFixtures";
import { WealthRouter } from "../../app/routes/WealthRouter";
import { StockDetailPage } from "./StockDetailPage";

const MAJOR_INDICES_PATH = "/api/v1/wealth/market/major-indices";
const MAJOR_INDEX_CODES = [
  "000001.SH", "399001.SZ", "399006.SZ", "000688.SH", "000300.SH",
  "000905.SH", "000852.SH", "899050.BJ", "000510.SH", "000016.SH",
];

function majorIndicesResponse(hasQuotes = true) {
  return Response.json({
    tradingDay: {
      tradeDate: "2026-09-02",
      prevTradeDate: "2026-09-01",
      market: "CN_A",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
    },
    pageStatus: { status: hasQuotes ? "PARTIAL" : "EMPTY", displayText: hasQuotes ? "部分指数数据缺失" : "模块数据为空" },
    majorIndices: {
      definition: { definitionKey: "CN_A_MAJOR_INDICES_V1", version: "1", fixedCount: 10 },
      // The API retains all configured rows and uses nulls for missing quotes.
      rows: MAJOR_INDEX_CODES.map((subjectCode, index) => {
        const hasQuote = hasQuotes && index === 0;
        return {
          subject: { subjectType: "index", subjectCode, subjectName: index === 0 ? "上证指数" : null },
          point: hasQuote ? 3825.76 : null,
          change: hasQuote ? 12.3 : null,
          changePct: hasQuote ? 0.45 : null,
          direction: hasQuote ? "UP" : "UNKNOWN",
        };
      }),
    },
  } satisfies MarketMajorIndicesResponse);
}

describe("StockDetailPage", () => {
  function mockStockDetailFetch({
    fail = false,
    supportsMinute = false,
    supportsTrendChannel = false,
    isAdded = false,
    failWatchlist = false,
    empty = false,
    emptyQuote = false,
    local = false,
    missingLocalQuote = false,
    missingLocalNineTurn = false,
  }: {
    fail?: boolean;
    supportsMinute?: boolean;
    supportsTrendChannel?: boolean;
    isAdded?: boolean;
    failWatchlist?: boolean;
    empty?: boolean;
    emptyQuote?: boolean;
    local?: boolean;
    missingLocalQuote?: boolean;
    missingLocalNineTurn?: boolean;
  } = {}) {
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
        availableMainOverlays: supportsTrendChannel ? ["MA", "BOLL", "TREND_CHANNEL"] : ["MA", "BOLL"],
        availableIndicatorTabs: ["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"],
      },
      capabilities: {
        supportsRealtime: false,
        supportsMinute,
        minuteFrequencies: supportsMinute ? [1, 5, 15, 30, 60, 90, 120] : [],
        supportsNineTurn: true,
        supportsTrendChannel,
        nineTurnPeriods: supportsMinute ? ["day", "30", "60", "90", "120"] : ["day"],
        supportsWeeklyMonthly: false,
        userActions: { watchlist: true, alert: false, tradePlan: false, diagnosis: false },
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
            trendChannel: { shortUpper: 19.2, shortLower: 18.9, longUpper: 19.3, longLower: 18.8 },
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
            trendChannel: { shortUpper: 19.2, shortLower: 18.9, longUpper: 19.3, longLower: 18.8 },
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
    const stockNews = {
      stockRef: { tsCode: "603806.SH", name: "福斯特" },
      items: [
        { newsId: "news-3", publishTime: "2026-05-29T16:00:03+08:00", title: "第三条新闻" },
        { newsId: "news-1", publishTime: "2026-05-29T16:00:01+08:00", title: "第一条新闻" },
        { newsId: "news-2", publishTime: "2026-05-29T16:00:02+08:00", title: "第二条新闻" },
      ],
      meta: { count: 3, limit: 50, startAt: "2026-06-23T00:00:00+08:00", endAt: "2026-08-23T00:00:00+08:00" },
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
    const dailyNineTurn = {
      subjectType: "stock",
      tsCode: "603806.SH",
      period: "day",
      markers: [
        {
          tradeDate: "2026-05-28",
          tradeTime: null,
          direction: "UP",
          sequenceNumber: 1,
          completed: false,
        },
        {
          tradeDate: "2026-05-29",
          tradeTime: null,
          direction: "UP",
          sequenceNumber: 9,
          completed: true,
        },
      ],
      latestMarker: {
        tradeDate: "2026-05-29",
        tradeTime: null,
        direction: "UP",
        sequenceNumber: 9,
        completed: true,
      },
      dataStatus: {
        status: "READY",
        code: null,
        message: null,
        expectedEndDate: "2026-05-29",
        observedEndDate: "2026-05-29",
      },
      meta: {
        sourceRowCount: 2,
        matchedRowCount: 2,
        missingRowCount: 0,
        markerCount: 2,
        limit: 300,
        hasMore: false,
        nextCursor: null,
        startDate: null,
        endDate: "2026-05-29",
        observedStartDate: "2026-05-28",
        observedEndDate: "2026-05-29",
        comparisonLag: 4,
        signalThreshold: 9,
        formulaVersion: 1,
      },
      debugInfo: null,
    };
    const minuteNineTurn = {
      ...dailyNineTurn,
      period: "30",
      markers: [{
        ...dailyNineTurn.markers[0],
        tradeDate: "2026-05-29",
        tradeTime: "2026-05-29T14:55:00+08:00",
      }],
      latestMarker: {
        ...dailyNineTurn.markers[0],
        tradeDate: "2026-05-29",
        tradeTime: "2026-05-29T14:55:00+08:00",
      },
      meta: {
        ...dailyNineTurn.meta,
        limit: 500,
        markerCount: 1,
      },
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      const url = String(input);
      const requestedCode = new URL(url).searchParams.get("tsCode");
      const requestedDay = new URL(url).searchParams.get("tradeDate") ?? "2026-05-31";
      const otherStock = requestedCode === "601878.SH"
        ? { tsCode: "601878.SH", symbol: "601878", name: "浙商证券" }
        : null;
      if (fail) return new Response(JSON.stringify({ code: "internal_error", message: "接口失败" }), { status: 500 });
      if (url.includes("/watchlist/stocks/")) {
        if (failWatchlist) return new Response(JSON.stringify({ code: "WL_QUERY_FAILED", message: "自选失败" }), { status: 500 });
        return new Response(JSON.stringify(options?.method === "PUT"
          ? { tsCode: "603806.SH", isAdded: true, groupIds: JSON.parse(String(options.body)).groupIds, createdCount: isAdded ? 0 : 1, removedCount: 0 }
          : { tsCode: "603806.SH", isAdded, groups: [{ groupId: 1, name: "我的自选", isDefault: true, color: null, selected: isAdded }, { groupId: 2, name: "观察", isDefault: false, color: "#F7C76B", selected: false }] }));
      }
      if (url.includes("/page-init")) {
        if (local) {
          const { quote, dataStatus, ...localInit } = pageInit;
          return Response.json({ ...localInit, pageContext: { ...pageInit.pageContext, tradeDate: requestedDay } });
        }
        if (emptyQuote) return Response.json({ ...pageInit, quote: null,
          dataStatus: { ...pageInit.dataStatus, status: "EMPTY", observedTradeDate: null } });
        return Response.json(otherStock ? { ...pageInit, stock: { ...pageInit.stock, ...otherStock } } : pageInit);
      }
      if (url.includes("/kline")) {
        if (empty) return Response.json({ ...kline, bars: [], meta: { ...kline.meta, count: 0 },
          ...(local ? { quote: null, nineTurnMarkers: [] } : {}),
          dataStatus: { ...kline.dataStatus, status: "EMPTY", observedTradeDate: null } });
        if (local && !missingLocalQuote) {
          const latest = { ...kline.bars.at(-1)!, close: 21.34 };
          return Response.json({
            ...kline,
            pageContext: { ...pageInit.pageContext, tradeDate: requestedDay },
            bars: [...kline.bars.slice(0, -1), latest],
            quote: { ...pageInit.quote, price: latest.close, close: latest.close },
            ...(!missingLocalNineTurn ? { nineTurnMarkers: [{
              tradeDate: latest.tradeDate, tradeTime: null, direction: "UP", sequenceNumber: 9, completed: true,
            }] } : {}),
            dataStatus: { ...kline.dataStatus, status: "DELAYED", expectedTradeDate: requestedDay },
          });
        }
        return Response.json({
          ...kline,
          ...(local ? { nineTurnMarkers: [] } : {}),
          ...(otherStock ? { stockRef: { tsCode: otherStock.tsCode, name: otherStock.name } } : {}),
        });
      }
      if (url.includes("/stock-detail/news")) return new Response(JSON.stringify(stockNews), { status: 200 });
      if (url.includes("/nine-turn")) {
        return Response.json(otherStock ? { ...dailyNineTurn, tsCode: otherStock.tsCode } : dailyNineTurn);
      }
      if (supportsMinute && url.includes("/stock-detail/minutes")) {
        const freq = Number(new URL(url).searchParams.get("freq"));
        const tradeTime = "2026-05-29T15:00:00+08:00";
        const marker = { ...minuteNineTurn.markers[0], tradeTime };
        return Response.json({
          ...minuteBars,
          freq,
          bars: minuteBars.bars.map((bar) => ({ ...bar, freq, tradeTime })),
          indicators: minuteIndicators.items.map((item) => ({ ...item, freq, tradeTime })),
          nineTurn: [30, 60, 90, 120].includes(freq)
            ? { ...minuteNineTurn, period: String(freq), markers: [marker], latestMarker: marker,
              meta: { ...minuteNineTurn.meta, sourceRowCount: 1, matchedRowCount: 1 } }
            : null,
        });
      }
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

  it.each([false, true])("shows a successful empty page without charts or layers (empty quote: %s)", async (emptyQuote) => {
    const fetchMock = mockStockDetailFetch({ empty: true, emptyQuote, supportsTrendChannel: true });
    render(<StockDetailPage tsCode="603806.SH" />);
    expect(await screen.findByLabelText("暂无行情信息")).toBeInTheDocument();
    expect(screen.getByText("暂无行情信息")).toBeInTheDocument();
    expect(screen.queryByText("股票详情加载失败")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("K线主图")).not.toBeInTheDocument();
    const urls = fetchMock.mock.calls.map(([url]) => String(url));
    expect(urls.filter(url => url.includes("/page-init"))).toHaveLength(1);
    expect(urls.filter(url => url.includes("/kline"))).toHaveLength(1);
    expect(urls.some(url => url.includes("/nine-turn") || url.includes("/trend-channel"))).toBe(false);
  });

  it("waits for the local page date, requests one daily batch, and displays the K-line quote", async () => {
    const detailFetch = mockStockDetailFetch({ local: true });
    const pageInit = deferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(String(input));
      if (url.pathname.endsWith("/page-init")) return pageInit.promise;
      if (url.pathname === MAJOR_INDICES_PATH) return Promise.resolve(majorIndicesResponse());
      return detailFetch(input, options);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<StockDetailPage tsCode="603806.SH" />);
    expect(fetchMock.mock.calls.map(([input]) => new URL(String(input)).pathname))
      .toEqual(["/api/v1/wealth/market/stock-detail/page-init"]);
    pageInit.resolve(await detailFetch(fetchMock.mock.calls[0][0]));

    expect(await screen.findByText("21.34", { selector: ".price" })).toBeInTheDocument();
    const matching = (suffix: string) => fetchMock.mock.calls
      .map(([input]) => new URL(String(input))).filter((url) => url.pathname.endsWith(suffix));
    expect(matching("/kline")).toHaveLength(1);
    expect(matching("/kline")[0].searchParams.get("tradeDate")).toBe("2026-05-31");
    expect(matching("/kline")[0].searchParams.get("endDate")).toBe("2026-05-31");
    expect(matching("/major-indices")[0].searchParams.get("tradeDate")).toBe("2026-05-31");
    expect(matching("/nine-turn")).toHaveLength(0);
    expect(screen.queryByText("当前窗口暂无九转标记")).not.toBeInTheDocument();
    const nineTurn = screen.getByRole("button", { name: "九转序列", pressed: true });
    fireEvent.click(nineTurn);
    fireEvent.click(nineTurn);
    expect(matching("/nine-turn")).toHaveLength(0);
    fireEvent.click(screen.getByRole("tab", { name: "新闻" }));
    await screen.findByText("第三条新闻");
    expect(matching("/news")[0].searchParams.get("endAt")).toBe("2026-06-01T00:00:00+08:00");
  });

  it("ignores a delayed daily response after changing the same stock's explicit date", async () => {
    const detailFetch = mockStockDetailFetch({ local: true });
    const oldKline = deferred<Response>();
    let oldSignal: AbortSignal | null | undefined;
    const fetchMock = vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      const url = new URL(String(input));
      if (url.pathname.endsWith("/kline") && url.searchParams.get("endDate") === "2026-05-30") {
        oldSignal = options?.signal;
        return oldKline.promise;
      }
      return detailFetch(input, options);
    });
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<StockDetailPage tsCode="603806.SH" tradeDate="2026-05-30" />);
    await waitFor(() => expect(oldSignal).toBeDefined());
    view.rerender(<StockDetailPage tsCode="603806.SH" tradeDate="2026-05-31" />);
    await screen.findByText("21.34", { selector: ".price" });
    expect(oldSignal?.aborted).toBe(true);
    await act(async () => oldKline.resolve(Response.json({ message: "上一日期不能覆盖当前页面" }, { status: 500 })));
    expect(screen.queryByText("上一日期不能覆盖当前页面")).not.toBeInTheDocument();
    expect(screen.getByText("21.34", { selector: ".price" })).toBeInTheDocument();
  });

  it("separates a local empty response from a nonempty response missing its quote", async () => {
    mockStockDetailFetch({ local: true, empty: true });
    const emptyView = render(<StockDetailPage tsCode="603806.SH" />);
    expect(await screen.findByLabelText("暂无行情信息")).toBeInTheDocument();
    emptyView.unmount();
    mockStockDetailFetch({ local: true, missingLocalQuote: true });
    render(<StockDetailPage tsCode="603806.SH" />);
    expect(await screen.findByText("股票日 K 首屏缺少盘口数据")).toBeInTheDocument();
  });

  it("rejects a local first page missing its nine-turn list", async () => {
    const requests = mockStockDetailFetch({ local: true, missingLocalNineTurn: true });
    render(<StockDetailPage tsCode="603806.SH" />);
    expect(await screen.findByText("股票日线回包缺少九转标记")).toBeInTheDocument();
    expect(requests.mock.calls.some(([input]) => String(input).includes("/stock-detail/nine-turn"))).toBe(false);
  });

  it("loads ticker data from the API independently after opening a stock from the default watchlist", async () => {
    const detailFetch = mockStockDetailFetch();
    const watchlistItem = item();
    const watchlist = page([item(1, {
      stock: { ...watchlistItem.stock, tsCode: "603806.SH", name: "福斯特" },
    })]);
    const detailIndices = deferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL, options?: RequestInit) => {
      const { pathname } = new URL(String(input));
      if (pathname.endsWith("/watchlist/groups")) {
        return Promise.resolve(Response.json({ groups: [watchlist.group], rules }));
      }
      if (pathname.endsWith("/watchlist/groups/1/items")) return Promise.resolve(Response.json(watchlist));
      if (pathname === MAJOR_INDICES_PATH) {
        if (window.location.pathname === "/wealth/market/watchlist") return Promise.resolve(majorIndicesResponse());
        return detailIndices.promise;
      }
      return detailFetch(input, options);
    });
    vi.stubGlobal("fetch", fetchMock);
    window.history.replaceState({}, "", "/wealth/market/watchlist");
    render(<AuthProvider><WealthRouter /></AuthProvider>);

    const tickers = () => within(screen.getByLabelText("主要指数行情条"));
    expect(await tickers().findByRole("button", { name: /上证指数/ })).toHaveTextContent("3825.76");
    fireEvent.click(await screen.findByRole("button", { name: "603806.SH" }));
    expect(window.location.pathname).toBe("/wealth/market/stock/603806.SH");
    expect(screen.getByLabelText("股票详情加载中")).toBeInTheDocument();
    expect(tickers().queryAllByRole("button")).toHaveLength(0);

    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    expect(tickers().queryAllByRole("button")).toHaveLength(0);
    detailIndices.resolve(majorIndicesResponse());
    const index = await tickers().findByRole("button", { name: /上证指数/ });
    expect(within(index).getByText("3825.76")).toHaveClass("up");
    expect(within(index).getByText("+0.45%")).toHaveClass("up");
    const indicesCalls = fetchMock.mock.calls.map(([url]) => new URL(String(url)))
      .filter(({ pathname }) => pathname === MAJOR_INDICES_PATH);
    expect(indicesCalls.map(({ search }) => search)).toEqual(["", "?tradeDate=2026-05-29"]);
  });

  it.each(["failed", "empty"])("keeps stock content available when the index response is %s", async (outcome) => {
    const detailFetch = mockStockDetailFetch();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
      if (new URL(String(input)).pathname === MAJOR_INDICES_PATH) {
        return outcome === "failed" ? new Response("{}", { status: 503 }) : majorIndicesResponse(false);
      }
      return detailFetch(input, options);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "乾坤行情" })).toBeInTheDocument();
    expect(within(screen.getByLabelText("主要指数行情条")).queryAllByRole("button")).toHaveLength(0);
    expect(fetchMock.mock.calls.filter(([url]) => new URL(String(url)).pathname === MAJOR_INDICES_PATH)).toHaveLength(1);
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
    expect(screen.getByRole("button", { name: "返回首页" })).toBeInTheDocument();
    expect(screen.getByLabelText("K线主图")).toBeInTheDocument();
    expect(screen.getByLabelText("右侧信息栏")).toBeInTheDocument();
    expect(screen.getAllByText("MA10:18.90").length).toBeGreaterThan(0);
    expect(screen.queryByText(/MA15/)).not.toBeInTheDocument();
    expect(screen.queryByText(/MA120/)).not.toBeInTheDocument();
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/stock-detail/nine-turn"),
      expect.anything(),
    ));
    const nineTurnRequest = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes("/stock-detail/nine-turn"));
    expect(new URL(String(nineTurnRequest?.[0])).searchParams.get("limit")).toBe("500");
  });

  it("loads membership, adds once and preserves default day/forward and other placeholders", async () => {
    const fetchMock = mockStockDetailFetch();
    render(<StockDetailPage tsCode="603806.SH" />);
    const button = await screen.findByRole("button", { name: "+自选" });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);
    const checkbox = await screen.findByRole("checkbox", { name: "观察" });
    expect(screen.getByRole("button", { name: "确认" })).toBeDisabled();
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "确认" }));
    expect(await screen.findByRole("button", { name: "已添加" })).toBeEnabled();
    const writeCall = fetchMock.mock.calls.find(([url, options]) => String(url).includes("/watchlist/") && options?.method === "PUT");
    expect(JSON.parse(String(writeCall?.[1]?.body))).toEqual({ groupIds: [2] });
    expect(fetchMock.mock.calls.filter(([url, options]) => String(url).includes("/watchlist/") && options?.method === "PUT")).toHaveLength(1);
    const klineUrl = new URL(String(fetchMock.mock.calls.find(([url]) => String(url).includes("/kline"))![0]));
    expect(klineUrl.searchParams.get("limit")).toBe("500");
    expect(klineUrl.searchParams.get("period")).toBe("day"); expect(klineUrl.searchParams.get("adjustment")).toBe("forward");
    fireEvent.click(screen.getByRole("button", { name: "+提醒" })); expect(screen.getByText("+提醒暂未开通")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "+交易计划" })); expect(screen.getByText("+交易计划暂未开通")).toBeInTheDocument();
  });

  it("allows already-added stock to reopen and keeps membership errors local to the action", async () => {
    mockStockDetailFetch({ isAdded: true });
    const view = render(<StockDetailPage tsCode="603806.SH" />);
    const added = await screen.findByRole("button", { name: "已添加" });
    expect(added).toBeEnabled(); fireEvent.click(added);
    expect(await screen.findByRole("checkbox", { name: "我的自选" })).toBeChecked();
    view.unmount();
    mockStockDetailFetch({ failWatchlist: true });
    render(<StockDetailPage tsCode="603806.SH" />);
    expect(await screen.findByText("自选失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+自选" })).toBeEnabled(); expect(screen.getByLabelText("K线主图")).toBeInTheDocument();
  });

  it("returns a direct stock detail visit to the Wealth overview", async () => {
    window.history.replaceState({}, "", "/wealth/market/stock/603806.SH");
    render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "返回首页" }));

    expect(window.location.pathname).toBe("/wealth/market/overview");
  });

  it("supports visible period, overlay, tab and toast interactions", async () => {
    const fetchMock = mockStockDetailFetch();
    render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "周K" }));
    expect(screen.getByText("周K 首期暂未接入真实数据")).toBeInTheDocument();

    expect(screen.queryByRole("combobox", { name: "主图指标切换" })).not.toBeInTheDocument();
    const requestCount = fetchMock.mock.calls.length;
    const ma = screen.getByRole("button", { name: "均线", pressed: true });
    fireEvent.click(ma);
    expect(within(screen.getByLabelText("K线主图")).queryAllByText(/^MA\d+:/)).toHaveLength(0);
    fireEvent.click(ma);
    expect(ma).toHaveAttribute("aria-pressed", "true");
    expect(fetchMock).toHaveBeenCalledTimes(requestCount);
    fireEvent.click(screen.getByRole("button", { name: "BOLL" }));
    expect(screen.getByText(/UPPER:/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "资料" }));
    expect(screen.getByText("公司资料、财务摘要与公告入口将在后续真实 API 方案中接入。")).toBeInTheDocument();

    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["盘口", "资料", "新闻"]);
    expect(fetchMock.mock.calls.map(([input]) => String(input)).some((url) => url.includes("/stock-detail/news"))).toBe(false);
    fireEvent.click(screen.getByRole("tab", { name: "新闻" }));
    expect(await screen.findByText("第三条新闻")).toBeInTheDocument();
    const newsRequests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes("/stock-detail/news"));
    expect(newsRequests).toHaveLength(1);
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "第三条新闻05-29",
      "第一条新闻05-29",
      "第二条新闻05-29",
    ]);

    fireEvent.click(screen.getByRole("button", { name: "主力密码" }));
    expect(screen.getByText("主力密码 指标暂未支持")).toBeInTheDocument();
  });

  it("loads the minute chart once with the anchored date and 500 bars", async () => {
    const fetchMock = mockStockDetailFetch({ supportsMinute: true });
    const { rerender } = render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    const expectAllOn = () => {
      for (const name of ["VOL", "MACD", "KDJ", "九转序列"]) {
        expect(screen.getByRole("button", { name, pressed: true })).toHaveClass("active");
      }
    };
    const expectSilentStructure = () => {
      const count = fetchMock.mock.calls.length;
      const structure = screen.getByRole("button", { name: "量化结构", pressed: false });
      expect(structure).toBeEnabled();
      fireEvent.click(structure);
      expect(structure).toHaveAttribute("aria-pressed", "false");
      expect(screen.queryByLabelText("量化结构(12,26,9)")).not.toBeInTheDocument();
      expect(screen.queryByText("最多展示3个技术指标，请取消一个后再打开")).not.toBeInTheDocument();
      expect(fetchMock).toHaveBeenCalledTimes(count);
    };
    expectAllOn();
    const nineTurn = () => screen.getByRole("button", { name: "九转序列" });
    const dailyRequests = fetchMock.mock.calls.length;
    fireEvent.click(nineTurn());
    expect(nineTurn()).toHaveAttribute("aria-pressed", "false");
    expect(fetchMock).toHaveBeenCalledTimes(dailyRequests);
    expectSilentStructure();
    fireEvent.click(screen.getByRole("button", { name: "KDJ", pressed: true }));
    expectSilentStructure();
    fireEvent.click(screen.getByRole("button", { name: "5分" }));
    expect(screen.getByText("正在加载 5 分钟行情…")).toBeInTheDocument();

    await waitFor(() => {
      const minuteRequests = fetchMock.mock.calls
        .map(([input]) => String(input))
        .filter((url) => url.includes("/stock-detail/minutes") || url.includes("/stock-detail/minute-indicators"));
      expect(minuteRequests).toHaveLength(1);
    });

    const minuteRequests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes("/stock-detail/minutes") || url.includes("/stock-detail/minute-indicators"));
    expect(minuteRequests[0]).toContain("freq=5");
    expect(minuteRequests[0]).toContain("endDate=2026-05-29");
    expect(minuteRequests[0]).toContain("limit=500");
    expect(minuteRequests[0]).toContain("/stock-detail/minutes");
    expect(await screen.findByLabelText("分钟图表区")).toBeInTheDocument();
    expect(screen.getByText("分钟K线")).toBeInTheDocument();
    expect(screen.queryByText("正在加载 5 分钟行情…")).not.toBeInTheDocument();
    const nineTurnMinuteRequests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => url.includes("/minute-nine-turn"));
    expect(nineTurnMinuteRequests).toHaveLength(0);
    expect(nineTurn()).toBeDisabled();
    expect(screen.getByRole("button", { name: "KDJ", pressed: false })).not.toHaveClass("active");
    expectSilentStructure();
    fireEvent.click(screen.getByRole("button", { name: "KDJ", pressed: false }));
    expectSilentStructure();
    fireEvent.click(screen.getByRole("button", { name: "KDJ", pressed: true }));
    const requestCount = fetchMock.mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "VOL", pressed: true }));
    fireEvent.click(screen.getByRole("button", { name: "MACD", pressed: true }));
    fireEvent.click(screen.getByRole("button", { name: "MACD", pressed: false }));
    expect(fetchMock).toHaveBeenCalledTimes(requestCount);

    fireEvent.click(screen.getByRole("button", { name: "15分" }));
    const otherMinuteBar = await screen.findByLabelText("股票分钟指标栏");
    expect(within(otherMinuteBar).getByRole("button", { name: "VOL", pressed: false })).toBeInTheDocument();
    expect(within(otherMinuteBar).getByRole("button", { name: "KDJ", pressed: false })).toBeInTheDocument();
    expect(within(otherMinuteBar).getByRole("button", { name: "MACD", pressed: true })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "日K" }));
    expect(screen.getByRole("button", { name: "KDJ", pressed: false })).toBeInTheDocument();
    expect(nineTurn()).toBeEnabled();
    expect(nineTurn()).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(screen.getByRole("button", { name: "5分" }));
    expect(await screen.findByRole("button", { name: "VOL", pressed: false })).toBeInTheDocument();
    const fiveMinuteRequests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => (url.includes("/stock-detail/minutes") || url.includes("/stock-detail/minute-indicators")) && url.includes("freq=5"));
    expect(fiveMinuteRequests).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "30分" }));
    await waitFor(() => expect(nineTurn()).toBeEnabled());
    expect(nineTurn()).toHaveAttribute("aria-pressed", "false");
    const minuteRequestsBeforeToggle = fetchMock.mock.calls.length;
    fireEvent.click(nineTurn());
    expect(nineTurn()).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(nineTurn());
    expect(fetchMock).toHaveBeenCalledTimes(minuteRequestsBeforeToggle);
    fireEvent.click(screen.getByRole("button", { name: "日K" }));

    rerender(<StockDetailPage tsCode="601878.SH" />);
    expect(await screen.findByText("浙商证券 601878.SH")).toBeInTheDocument();
    expectAllOn();
    rerender(<StockDetailPage tsCode="603806.SH" />);
    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    expectAllOn();
  });

  it("uses daily response rails when toggled without sending a trend request", async () => {
    const fetchMock = mockStockDetailFetch({ supportsTrendChannel: true });
    render(<StockDetailPage tsCode="603806.SH" />);
    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    for (const label of ["趋势通道", "均线", "趋势通道"]) {
      fireEvent.click(screen.getByRole("button", { name: label }));
    }
    expect(screen.getByText("短上:19.20")).toBeInTheDocument();
    expect(screen.getByLabelText("K线主图")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/trend-channel"))).toBe(false);
  });

  it("does not expose or request stock trend channel when capability is false", async () => {
    const fetchMock = mockStockDetailFetch({ supportsTrendChannel: false });
    render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "趋势通道" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/trend-channel"))).toBe(false);
  });

  it("draws the four rails returned in the daily Kline response", async () => {
    const fetchMock = mockStockDetailFetch({ supportsTrendChannel: true });
    render(<StockDetailPage tsCode="603806.SH" />);
    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "趋势通道" }));
    expect(screen.getByText("短上:19.20")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("/trend-channel"))).toBe(false);
  });

  it.each([
    ["30分", 30],
    ["60分", 60],
    ["90分", 90],
    ["120分", 120],
  ] as const)("uses the single chart response for nine-turn on %s", async (label, freq) => {
    const fetchMock = mockStockDetailFetch({ supportsMinute: true });
    render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByText("福斯特 603806.SH")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: label }));

    expect(await screen.findByLabelText("股票分钟指标栏")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "九转序列" })).toBeEnabled();
    const requests = fetchMock.mock.calls
      .map(([input]) => String(input))
      .filter((url) => /\/stock-detail\/minute/.test(url));
    expect(requests).toHaveLength(1);
    expect(requests[0]).toContain("/stock-detail/minutes?");
    expect(requests[0]).toContain("freq=" + freq);
    expect(requests[0]).toContain("endDate=2026-05-29");
    expect(requests[0]).toContain("limit=500");
  });

  it("keeps the anchored index data visible when daily K-line fails after page-init", async () => {
    const detailFetch = mockStockDetailFetch();
    vi.stubGlobal("fetch", (input: RequestInfo | URL, options?: RequestInit) => {
      const { pathname } = new URL(String(input));
      if (pathname === MAJOR_INDICES_PATH) return Promise.resolve(majorIndicesResponse());
      if (pathname.endsWith("/kline")) {
        return Promise.resolve(Response.json({ message: "接口失败" }, { status: 500 }));
      }
      return detailFetch(input, options);
    });

    render(<StockDetailPage tsCode="603806.SH" />);

    expect(await screen.findByLabelText("股票详情加载失败")).toBeInTheDocument();
    expect(screen.getByText("接口失败")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByLabelText("K线主图")).not.toBeInTheDocument());
    expect(await screen.findByRole("button", { name: /上证指数/ })).toHaveTextContent("3825.76");
  });

  it("sends no dated follow-up requests when page-init fails", async () => {
    const fetchMock = mockStockDetailFetch({ fail: true });
    render(<StockDetailPage tsCode="603806.SH" />);
    expect(await screen.findByLabelText("股票详情加载失败")).toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => new URL(String(input)).pathname))
      .toEqual(["/api/v1/wealth/market/stock-detail/page-init"]);
  });
});
