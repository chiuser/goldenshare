import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { marketOverviewModuleSources } from "../../features/market-overview/api/moduleSources";
import { MarketOverviewPage } from "./MarketOverviewPage";

const summaryFiveCards = {
  tradingDay: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-04-28T15:05:00+08:00" },
  marketSummary: {
    definition: {
      definitionKey: "CN_A_SUMMARY_V1",
      version: "1.0.0",
      cardCount: 5,
      textPosition: "BOTTOM_FIXED",
      layoutVariant: "FIVE_SINGLE_ROW",
    },
    cards: [
      { cardKey: "majorIndexUpCount", label: "主要指数涨跌比", value: "8:2", subText: "上涨数量:下跌数量", direction: "UP" },
      { cardKey: "riseFallCount", label: "上涨 / 下跌", value: "3421 / 1488", subText: "平盘 219", direction: "UP" },
      { cardKey: "turnoverTotal", label: "成交总额", value: "10523亿", subText: "较昨日 +7.15%", direction: "UP" },
      { cardKey: "marketNetFlow", label: "大盘资金", value: "-52.8亿", subText: "净流出", direction: "DOWN" },
      { cardKey: "limitUpDown", label: "涨停 / 跌停", value: "59 / 8", subText: "炸板 27", direction: "UP" },
    ],
    textCard: {
      title: "截至收盘，A 股主要指数多数上涨。",
      content: "全市场上涨家数多于下跌家数，成交额较上一交易日放大。",
      templateKey: "objective_close_v1",
    },
  },
};

const summarySixCards = {
  ...summaryFiveCards,
  marketSummary: {
    ...summaryFiveCards.marketSummary,
    definition: {
      ...summaryFiveCards.marketSummary.definition,
      cardCount: 6,
      layoutVariant: "SIX_TWO_ROWS",
    },
    cards: [
      summaryFiveCards.marketSummary.cards[0],
      summaryFiveCards.marketSummary.cards[1],
      { cardKey: "flatCount", label: "平盘家数", value: "219", subText: "当前日统计", direction: "FLAT" },
      summaryFiveCards.marketSummary.cards[2],
      summaryFiveCards.marketSummary.cards[3],
      summaryFiveCards.marketSummary.cards[4],
    ],
  },
};

const majorIndicesPayload = {
  tradingDay: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-04-28T15:05:00+08:00" },
  majorIndices: {
    definition: {
      definitionKey: "CN_A_MAJOR_INDICES_V1",
      version: "1.0.0",
      fixedCount: 10,
    },
    rows: [
      { subject: { subjectType: "index", subjectCode: "000001.SH", subjectName: "上证指数" }, point: 3128.42, change: 28.66, changePct: 0.92, amount: 100, direction: "UP" },
      { subject: { subjectType: "index", subjectCode: "399001.SZ", subjectName: "深证成指" }, point: 9842.15, change: -34.21, changePct: -0.35, amount: 100, direction: "DOWN" },
      { subject: { subjectType: "index", subjectCode: "399006.SZ", subjectName: "创业板指" }, point: 1986.22, change: 22.03, changePct: 1.12, amount: 100, direction: "UP" },
      { subject: { subjectType: "index", subjectCode: "000688.SH", subjectName: "科创50" }, point: 921.56, change: -1.66, changePct: -0.18, amount: 100, direction: "DOWN" },
      { subject: { subjectType: "index", subjectCode: "000300.SH", subjectName: "沪深300" }, point: 3726.84, change: 26.58, changePct: 0.72, amount: 100, direction: "UP" },
      { subject: { subjectType: "index", subjectCode: "000905.SH", subjectName: "中证500" }, point: 5642.33, change: 58.65, changePct: 1.05, amount: 100, direction: "UP" },
      { subject: { subjectType: "index", subjectCode: "000852.SH", subjectName: "中证1000" }, point: 5948.17, change: 86.7, changePct: 1.48, amount: 100, direction: "UP" },
      { subject: { subjectType: "index", subjectCode: "899050.BJ", subjectName: "北证50" }, point: 1196.35, change: 24.15, changePct: 2.06, amount: 100, direction: "UP" },
      { subject: { subjectType: "index", subjectCode: "000510.SH", subjectName: "中证A500" }, point: 4683.91, change: 38.56, changePct: 0.83, amount: 100, direction: "UP" },
      { subject: { subjectType: "index", subjectCode: "000016.SH", subjectName: "上证50" }, point: 2542.08, change: 10.66, changePct: 0.42, amount: 100, direction: "UP" },
    ],
  },
};

const breadthPayload = {
  tradingDay: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-04-28T15:05:00+08:00" },
  breadth: {
    tradeDate: "2026-04-28",
    metrics: {
      upCount: 3421,
      downCount: 1488,
      flatCount: 219,
      redRate: 66.71,
    },
    historyByRange: {
      "1m": [
        { tradeDate: "2026-04-27", upCount: 3200, downCount: 1600 },
        { tradeDate: "2026-04-28", upCount: 3421, downCount: 1488 },
      ],
      "3m": [
        { tradeDate: "2026-03-03", upCount: 2500, downCount: 2100 },
        { tradeDate: "2026-04-28", upCount: 3421, downCount: 1488 },
      ],
    },
  },
};

const stylePayload = {
  tradingDay: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-04-28T15:05:00+08:00" },
  style: {
    definition: {
      definitionKey: "CN_A_MARKET_STYLE_V1",
      version: "1.0.0",
      fixedCardCount: 3,
    },
    cards: [
      { cardKey: "largeCap", label: "大盘股平均涨跌幅", valuePct: 0.72, sourceText: "沪深300口径", direction: "UP" },
      { cardKey: "smallCap", label: "小盘股平均涨跌幅", valuePct: 1.48, sourceText: "中证1000口径", direction: "UP" },
      { cardKey: "median", label: "涨跌中位数", valuePct: 0.48, sourceText: "全市场样本", direction: "UP" },
    ],
    historyByRange: {
      oneMonth: [
        { tradeDate: "2026-04-27", largePct: 0.52, smallPct: 1.21, medianPct: 0.31 },
        { tradeDate: "2026-04-28", largePct: 0.72, smallPct: 1.48, medianPct: 0.48 },
      ],
      threeMonth: [
        { tradeDate: "2026-03-03", largePct: -0.12, smallPct: 0.26, medianPct: 0.04 },
        { tradeDate: "2026-04-28", largePct: 0.72, smallPct: 1.48, medianPct: 0.48 },
      ],
    },
  },
};

const turnoverPayload = {
  tradingDay: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-04-28T15:05:00+08:00" },
  turnover: {
    tradeDate: "2026-04-28",
    metrics: {
      todayAmount: 1052300000,
      prevAmount: 982100000,
      amountDelta: 70200000,
      amountDeltaPct: 7.15,
      avg5dAmount: 1018000000,
      avg20dAmount: 936000000,
      unit: "thousand_yuan",
    },
    intradayCumulative: [
      { time: "09:30", cumAmount: 0 },
      { time: "10:30", cumAmount: 315000000 },
      { time: "11:30", cumAmount: 562000000 },
      { time: "14:00", cumAmount: 828000000 },
      { time: "15:00", cumAmount: 1052300000 },
    ],
    historyByRange: {
      oneMonth: [
        { tradeDate: "2026-04-27", amount: 982100000 },
        { tradeDate: "2026-04-28", amount: 1052300000 },
      ],
      threeMonth: [
        { tradeDate: "2026-03-03", amount: 865000000 },
        { tradeDate: "2026-04-28", amount: 1052300000 },
      ],
    },
  },
};

const leaderboardsPayload = {
  tradingDay: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: { status: "READY", displayText: "事实聚合已就绪", asOfTime: "2026-04-28T15:05:00+08:00" },
  definitions: [
    { boardKey: "gainers", boardLabel: "涨幅榜" },
    { boardKey: "losers", boardLabel: "跌幅榜" },
    { boardKey: "amount", boardLabel: "成交额榜" },
    { boardKey: "turnover", boardLabel: "换手榜" },
    { boardKey: "volumeRatio", boardLabel: "量比榜" },
    { boardKey: "popularity", boardLabel: "人气榜" },
    { boardKey: "surge", boardLabel: "飙升榜" },
  ],
  boards: [
    "gainers",
    "losers",
    "amount",
    "turnover",
    "volumeRatio",
    "popularity",
    "surge",
  ].map((boardKey, boardIndex) => ({
    boardKey,
    boardLabel: ["涨幅榜", "跌幅榜", "成交额榜", "换手榜", "量比榜", "人气榜", "飙升榜"][boardIndex],
    status: "READY",
    expectedTradeDate: "2026-04-28",
    observedTradeDate: "2026-04-28",
    lagDays: 0,
    rows: Array.from({ length: 10 }, (_, index) => ({
      rank: index + 1,
      subject: {
        subjectType: "stock",
        subjectCode: `0000${index + 1}.SZ`,
        subjectName: `个股${index + 1}`,
      },
      metrics: {
        latestPrice: 10 + index,
        changePct: 1 + index * 0.1,
        turnoverRate: 2 + index * 0.1,
        volumeRatio: 1 + index * 0.1,
        volume: 100000 + index * 1000,
        amount: 30000000 + index * 100000,
        direction: "UP",
      },
    })),
  })),
};

const pageContextPayload = {
  pageContext: {
    market: "CN_A",
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
    generatedAt: "2026-04-28T15:05:00+08:00",
    source: "explicit",
  },
};

function toUrlString(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function responseJson(payload: unknown): Response {
  return {
    ok: true,
    json: async () => payload,
  } as Response;
}

function maybeLeaderboardsResponse(url: string): Promise<Response> | null {
  if (!url.includes("/api/v1/wealth/market/leaderboards")) return null;
  return Promise.resolve(responseJson(leaderboardsPayload));
}

function maybeContextResponse(url: string): Promise<Response> | null {
  if (!url.includes("/api/v1/wealth/market/context")) return null;
  return Promise.resolve(responseJson(pageContextPayload));
}

function mockSuccessfulMarketFetch(
  summaryPayload = summaryFiveCards,
  majorPayload = majorIndicesPayload,
  breadthPayloadInput = breadthPayload,
  stylePayloadInput = stylePayload,
  turnoverPayloadInput = turnoverPayload,
  leaderboardsPayloadInput = leaderboardsPayload,
) {
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = toUrlString(input);
    const contextResponse = maybeContextResponse(url);
    if (contextResponse) return contextResponse;
    if (url.includes("/api/v1/wealth/market/summary")) {
      return responseJson(summaryPayload);
    }
    if (url.includes("/api/v1/wealth/market/major-indices")) {
      return responseJson(majorPayload);
    }
    if (url.includes("/api/v1/wealth/market/breadth")) {
      return responseJson(breadthPayloadInput);
    }
    if (url.includes("/api/v1/wealth/market/style")) {
      return responseJson(stylePayloadInput);
    }
    if (url.includes("/api/v1/wealth/market/turnover")) {
      return responseJson(turnoverPayloadInput);
    }
    if (url.includes("/api/v1/wealth/market/leaderboards")) {
      return responseJson(leaderboardsPayloadInput);
    }
    throw new Error(`unexpected url: ${url}`);
  });
}

describe("MarketOverviewPage", () => {
  const originalLimitUpSource = marketOverviewModuleSources.limitUp;
  const originalMoneyFlowSource = marketOverviewModuleSources.moneyFlow;
  const originalStreakLadderSource = marketOverviewModuleSources.streakLadder;
  const originalSectorsSource = marketOverviewModuleSources.sectors;
  beforeEach(() => {
    marketOverviewModuleSources.limitUp = "mock";
    marketOverviewModuleSources.moneyFlow = "mock";
    marketOverviewModuleSources.streakLadder = "mock";
    marketOverviewModuleSources.sectors = "mock";
    mockSuccessfulMarketFetch();
  });

  afterEach(() => {
    marketOverviewModuleSources.limitUp = originalLimitUpSource;
    marketOverviewModuleSources.moneyFlow = originalMoneyFlowSource;
    marketOverviewModuleSources.streakLadder = originalStreakLadderSource;
    marketOverviewModuleSources.sectors = originalSectorsSource;
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.history.pushState({}, "", "/");
  });

  it("renders the V1.1 market overview structure", async () => {
    render(<MarketOverviewPage />);

    expect(await screen.findByRole("heading", { name: "市场总览" })).toBeInTheDocument();
    expect(screen.getByText("交易日 2026-04-28")).toBeInTheDocument();
    expect(screen.getByText("2026-04-28 15:05:00")).toBeInTheDocument();
    expect(screen.getByLabelText("TopMarketBar")).toBeInTheDocument();
    expect(screen.getByLabelText("今日市场客观总结")).toBeInTheDocument();
    expect(screen.getByLabelText("主要指数")).toBeInTheDocument();
    expect(screen.getByLabelText("涨跌停统计与分布")).toBeInTheDocument();
    expect(screen.getByLabelText("板块速览")).toBeInTheDocument();
  });

  it("keeps leaderboard Top10 columns and range switching behavior", async () => {
    render(<MarketOverviewPage />);

    const table = await screen.findByRole("table", { name: "个股榜单" });
    ["排名", "股票", "最新价", "涨跌幅", "换手率", "量比", "成交量", "成交额"].forEach((column) => {
      expect(within(table).getByText(column)).toBeInTheDocument();
    });
    ["涨幅榜", "跌幅榜", "成交额榜", "换手榜", "量比榜", "人气榜", "飙升榜"].forEach((tab) => {
      expect(screen.getByRole("button", { name: tab })).toBeInTheDocument();
    });
    expect(within(table).getAllByRole("row")).toHaveLength(11);

    fireEvent.click(screen.getByRole("button", { name: "量比榜" }));
    expect(within(table).getAllByRole("row")).toHaveLength(11);

    fireEvent.click(screen.getAllByRole("button", { name: "3个月" })[0]);
    expect(screen.getAllByRole("button", { name: "3个月" })[0]).toHaveClass("active");
  });

  it("renders sector matrix and heatmap exactly as the showcase requires", async () => {
    render(<MarketOverviewPage />);

    await screen.findByRole("heading", { name: "市场总览" });
    expect(screen.getByText("行业涨幅前五")).toBeInTheDocument();
    expect(screen.getByText("资金流出前五")).toBeInTheDocument();
    expect(screen.getAllByLabelText(/^板块热力图-/)).toHaveLength(20);
  });

  it("uses lightweight toast for reserved navigation feedback", async () => {
    render(<MarketOverviewPage />);

    fireEvent.click(await screen.findByRole("button", { name: /手动刷新/ }));
    expect(screen.getByRole("button", { name: "刷新中" })).toBeInTheDocument();
  });

  it("summary module smoke supports both 5-card and 6-card layouts", async () => {
    vi.restoreAllMocks();
    mockSuccessfulMarketFetch(summaryFiveCards);

    const first = render(<MarketOverviewPage />);
    const summarySection = await screen.findByLabelText("今日市场客观总结");
    await waitFor(() => {
      expect(summarySection.querySelectorAll(".fact-card")).toHaveLength(5);
    });
    expect(summarySection.querySelector(".summary-facts-v2")?.classList.contains("six")).toBe(false);
    first.unmount();

    vi.restoreAllMocks();
    mockSuccessfulMarketFetch(summarySixCards);
    render(<MarketOverviewPage />);

    const summarySectionSix = await screen.findByLabelText("今日市场客观总结");
    await waitFor(() => {
      expect(summarySectionSix.querySelectorAll(".fact-card")).toHaveLength(6);
    });
    expect(summarySectionSix.querySelector(".summary-facts-v2")?.classList.contains("six")).toBe(true);
  });

  it("shows loading before real summary is returned, without rendering mock summary facts", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    let resolveSummaryFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    fetchMock.mockImplementation((input) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/summary")) {
        return new Promise<Response>((resolve) => {
          resolveSummaryFetch = resolve;
        });
      }
      const leaderboardsResponse = maybeLeaderboardsResponse(url);
      if (leaderboardsResponse) return leaderboardsResponse;
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    render(<MarketOverviewPage />);

    const summarySection = await screen.findByLabelText("今日市场客观总结");
    expect(within(summarySection).getByText("loading")).toBeInTheDocument();
    expect(summarySection.querySelectorAll(".fact-card")).toHaveLength(0);

    if (typeof resolveSummaryFetch !== "function") {
      throw new Error("summary fetch resolver is missing");
    }
    resolveSummaryFetch(responseJson(summaryFiveCards));

    await waitFor(() => {
      expect(summarySection.querySelectorAll(".fact-card")).toHaveLength(5);
    });
  });

  it("shows error state when summary request exceeds 5 seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    fetchMock.mockImplementation((input, init) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      const signal = (init as RequestInit | undefined)?.signal;
      return new Promise<Response>((_, reject) => {
        signal?.addEventListener(
          "abort",
          () => reject(new DOMException("The operation was aborted.", "AbortError")),
          { once: true },
        );
      });
    });

    const rendered = render(<MarketOverviewPage />);
    await act(async () => {
      await Promise.resolve();
    });

    const summarySection = rendered.container.querySelector<HTMLElement>('[aria-label="今日市场客观总结"]');
    expect(summarySection).not.toBeNull();
    if (!summarySection) {
      throw new Error("summary section not found");
    }
    expect(within(summarySection).getByText("loading")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(summarySection).getByText("请求超时：/api/v1/wealth/market/summary")).toBeInTheDocument();
    expect(within(summarySection).getByText("error")).toBeInTheDocument();
  }, 15000);

  it("shows loading before real major indices are returned, without rendering mock index cards", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    let resolveMajorFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    fetchMock.mockImplementation((input) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return new Promise<Response>((resolve) => {
          resolveMajorFetch = resolve;
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    render(<MarketOverviewPage />);

    const majorSection = await screen.findByLabelText("主要指数");
    expect(within(majorSection).getByText("loading")).toBeInTheDocument();
    expect(majorSection.querySelectorAll(".index-card")).toHaveLength(0);

    if (typeof resolveMajorFetch !== "function") {
      throw new Error("major indices fetch resolver is missing");
    }
    resolveMajorFetch(responseJson(majorIndicesPayload));

    await waitFor(() => {
      expect(majorSection.querySelectorAll(".index-card")).toHaveLength(10);
    });
  });

  it("uses major-indices real data in header ticker strip when available", async () => {
    render(<MarketOverviewPage />);

    const topBar = await screen.findByLabelText("TopMarketBar");
    await waitFor(() => {
      expect(within(topBar).getAllByText("中证A500").length).toBeGreaterThan(0);
    });
  });

  it("falls back to overview ticker strip when major-indices request fails", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    fetchMock.mockImplementation((input) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.reject(new Error("major indices failed"));
      }
      const leaderboardsResponse = maybeLeaderboardsResponse(url);
      if (leaderboardsResponse) return leaderboardsResponse;
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    render(<MarketOverviewPage />);

    const topBar = await screen.findByLabelText("TopMarketBar");
    await waitFor(() => {
      expect(within(topBar).getAllByText("中证1000").length).toBeGreaterThan(0);
    });
    expect(within(topBar).queryByText("中证A500")).not.toBeInTheDocument();
  });

  it("shows error state when major indices request exceeds 5 seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    fetchMock.mockImplementation((input, init) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        const signal = (init as RequestInit | undefined)?.signal;
        return new Promise<Response>((_, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("The operation was aborted.", "AbortError")),
            { once: true },
          );
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    const rendered = render(<MarketOverviewPage />);
    await act(async () => {
      await Promise.resolve();
    });

    const majorSection = rendered.container.querySelector<HTMLElement>('[aria-label="主要指数"]');
    expect(majorSection).not.toBeNull();
    if (!majorSection) {
      throw new Error("major indices section not found");
    }
    expect(within(majorSection).getByText("loading")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(majorSection).getByText("请求超时：/api/v1/wealth/market/major-indices")).toBeInTheDocument();
    expect(within(majorSection).getByText("error")).toBeInTheDocument();
  }, 15000);

  it("shows loading before real breadth is returned, without rendering mock breadth metrics", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    let resolveBreadthFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    fetchMock.mockImplementation((input) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return new Promise<Response>((resolve) => {
          resolveBreadthFetch = resolve;
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    render(<MarketOverviewPage />);

    const breadthSection = await screen.findByLabelText("涨跌分布");
    expect(within(breadthSection).getByText("loading")).toBeInTheDocument();
    expect(breadthSection.querySelectorAll(".mini-metrics .metric-card")).toHaveLength(0);

    if (typeof resolveBreadthFetch !== "function") {
      throw new Error("breadth fetch resolver is missing");
    }
    resolveBreadthFetch(responseJson(breadthPayload));

    await waitFor(() => {
      expect(breadthSection.querySelectorAll(".mini-metrics .metric-card")).toHaveLength(3);
    });
  });

  it("shows error state when breadth request exceeds 5 seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    fetchMock.mockImplementation((input, init) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        const signal = (init as RequestInit | undefined)?.signal;
        return new Promise<Response>((_, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("The operation was aborted.", "AbortError")),
            { once: true },
          );
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    const rendered = render(<MarketOverviewPage />);
    await act(async () => {
      await Promise.resolve();
    });

    const breadthSection = rendered.container.querySelector<HTMLElement>('[aria-label="涨跌分布"]');
    expect(breadthSection).not.toBeNull();
    if (!breadthSection) {
      throw new Error("breadth section not found");
    }
    expect(within(breadthSection).getByText("loading")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(breadthSection).getByText("请求超时：/api/v1/wealth/market/breadth")).toBeInTheDocument();
    expect(within(breadthSection).getByText("error")).toBeInTheDocument();
  }, 15000);

  it("shows loading before real style is returned, without rendering mock style metrics", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    let resolveStyleFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    fetchMock.mockImplementation((input) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return new Promise<Response>((resolve) => {
          resolveStyleFetch = resolve;
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    render(<MarketOverviewPage />);

    const styleSection = await screen.findByLabelText("市场风格");
    expect(within(styleSection).getByText("loading")).toBeInTheDocument();
    expect(styleSection.querySelectorAll(".mini-metrics .metric-card")).toHaveLength(0);

    if (typeof resolveStyleFetch !== "function") {
      throw new Error("style fetch resolver is missing");
    }
    resolveStyleFetch(responseJson(stylePayload));

    await waitFor(() => {
      expect(styleSection.querySelectorAll(".mini-metrics .metric-card")).toHaveLength(3);
    });
  });

  it("shows error state when style request exceeds 5 seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    fetchMock.mockImplementation((input, init) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        const signal = (init as RequestInit | undefined)?.signal;
        return new Promise<Response>((_, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("The operation was aborted.", "AbortError")),
            { once: true },
          );
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    const rendered = render(<MarketOverviewPage />);
    await act(async () => {
      await Promise.resolve();
    });

    const styleSection = rendered.container.querySelector<HTMLElement>('[aria-label="市场风格"]');
    expect(styleSection).not.toBeNull();
    if (!styleSection) {
      throw new Error("style section not found");
    }
    expect(within(styleSection).getByText("loading")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(styleSection).getByText("请求超时：/api/v1/wealth/market/style")).toBeInTheDocument();
    expect(within(styleSection).getByText("error")).toBeInTheDocument();
  }, 15000);

  it("shows loading before real turnover is returned, without rendering mock turnover metrics", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    let resolveTurnoverFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    fetchMock.mockImplementation((input) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return new Promise<Response>((resolve) => {
          resolveTurnoverFetch = resolve;
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    render(<MarketOverviewPage />);

    const turnoverSection = await screen.findByLabelText("成交额总览");
    expect(within(turnoverSection).getByText("loading")).toBeInTheDocument();
    expect(turnoverSection.querySelectorAll(".mini-metrics .metric-card")).toHaveLength(0);

    if (typeof resolveTurnoverFetch !== "function") {
      throw new Error("turnover fetch resolver is missing");
    }
    resolveTurnoverFetch(responseJson(turnoverPayload));

    await waitFor(() => {
      expect(turnoverSection.querySelectorAll(".mini-metrics .metric-card")).toHaveLength(4);
    });
  });

  it("shows error state when turnover request exceeds 5 seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    fetchMock.mockImplementation((input, init) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        const signal = (init as RequestInit | undefined)?.signal;
        return new Promise<Response>((_, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("The operation was aborted.", "AbortError")),
            { once: true },
          );
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    const rendered = render(<MarketOverviewPage />);
    await act(async () => {
      await Promise.resolve();
    });

    const turnoverSection = rendered.container.querySelector<HTMLElement>('[aria-label="成交额总览"]');
    expect(turnoverSection).not.toBeNull();
    if (!turnoverSection) {
      throw new Error("turnover section not found");
    }
    expect(within(turnoverSection).getByText("loading")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(turnoverSection).getByText("请求超时：/api/v1/wealth/market/turnover")).toBeInTheDocument();
    expect(within(turnoverSection).getByText("error")).toBeInTheDocument();
  }, 15000);

  it("shows loading before real leaderboards are returned, without rendering leaderboard table", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    let resolveLeaderboardsFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    fetchMock.mockImplementation((input) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/leaderboards")) {
        return new Promise<Response>((resolve) => {
          resolveLeaderboardsFetch = resolve;
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    render(<MarketOverviewPage />);

    const leaderboardSection = await screen.findByLabelText("榜单速览");
    expect(within(leaderboardSection).getByText("loading")).toBeInTheDocument();
    expect(within(leaderboardSection).queryByRole("table", { name: "个股榜单" })).toBeNull();

    if (typeof resolveLeaderboardsFetch !== "function") {
      throw new Error("leaderboards fetch resolver is missing");
    }
    resolveLeaderboardsFetch(responseJson(leaderboardsPayload));

    await waitFor(() => {
      const table = within(leaderboardSection).getByRole("table", { name: "个股榜单" });
      expect(within(table).getAllByRole("row")).toHaveLength(11);
    });
  });

  it("shows error state when leaderboards request exceeds 5 seconds", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    fetchMock.mockImplementation((input, init) => {
      const url = toUrlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return Promise.resolve(responseJson(summaryFiveCards));
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return Promise.resolve(responseJson(majorIndicesPayload));
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return Promise.resolve(responseJson(breadthPayload));
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return Promise.resolve(responseJson(stylePayload));
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return Promise.resolve(responseJson(turnoverPayload));
      }
      if (url.includes("/api/v1/wealth/market/leaderboards")) {
        const signal = (init as RequestInit | undefined)?.signal;
        return new Promise<Response>((_, reject) => {
          signal?.addEventListener(
            "abort",
            () => reject(new DOMException("The operation was aborted.", "AbortError")),
            { once: true },
          );
        });
      }
      return Promise.reject(new Error(`unexpected url: ${url}`));
    });

    const rendered = render(<MarketOverviewPage />);
    await act(async () => {
      await Promise.resolve();
    });

    const leaderboardSection = rendered.container.querySelector<HTMLElement>('[aria-label="榜单速览"]');
    expect(leaderboardSection).not.toBeNull();
    if (!leaderboardSection) {
      throw new Error("leaderboards section not found");
    }
    expect(within(leaderboardSection).getByText("loading")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(leaderboardSection).getByText("请求超时：/api/v1/wealth/market/leaderboards")).toBeInTheDocument();
    expect(within(leaderboardSection).getByText("error")).toBeInTheDocument();
  }, 15000);

  it("stops real module requests when page context fails", async () => {
    const requestUrls: string[] = [];
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input) => {
      const url = toUrlString(input);
      requestUrls.push(url);
      if (url.includes("/api/v1/wealth/market/context")) {
        return {
          ok: false,
          status: 503,
          json: async () => ({ code: "503001", message: "context unavailable" }),
        } as Response;
      }
      return responseJson(summaryFiveCards);
    });

    render(<MarketOverviewPage />);

    expect(await screen.findByText("页面时间上下文加载失败")).toBeInTheDocument();
    expect(screen.getByText("context unavailable")).toBeInTheDocument();
    expect(requestUrls).toEqual([expect.stringContaining("/api/v1/wealth/market/context")]);
  });

  it("uses page-level debug switch for summary, major-indices, breadth, style, turnover and leaderboards modules", async () => {
    window.history.pushState({}, "", "/market/overview?debug=1");
    const requestUrls: string[] = [];
    const fetchMock = vi.spyOn(globalThis, "fetch");
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input) => {
      const url = toUrlString(input);
      requestUrls.push(url);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/summary")) {
        return responseJson({
          ...summaryFiveCards,
          debugInfo: {
            modules: [
              {
                moduleKey: "marketSummary",
                expectedTradeDate: "2026-04-28",
                observedTradeDate: "2026-04-28",
                lagDays: 0,
                status: "READY",
                note: "facts ready",
              },
            ],
            exceptions: [],
          },
        });
      }
      if (url.includes("/api/v1/wealth/market/major-indices")) {
        return responseJson({
          ...majorIndicesPayload,
          debugInfo: {
            modules: [
              {
                moduleKey: "majorIndices",
                expectedTradeDate: "2026-04-28",
                observedTradeDate: "2026-04-28",
                lagDays: 0,
                status: "READY",
                note: "facts ready",
              },
            ],
            exceptions: [],
          },
        });
      }
      if (url.includes("/api/v1/wealth/market/breadth")) {
        return responseJson({
          ...breadthPayload,
          debugInfo: {
            modules: [
              {
                moduleKey: "breadth",
                expectedTradeDate: "2026-04-28",
                observedTradeDate: "2026-04-28",
                lagDays: 0,
                status: "READY",
                note: "facts ready",
              },
            ],
            exceptions: [],
          },
        });
      }
      if (url.includes("/api/v1/wealth/market/style")) {
        return responseJson({
          ...stylePayload,
          debugInfo: {
            modules: [
              {
                moduleKey: "marketStyle",
                expectedTradeDate: "2026-04-28",
                observedTradeDate: "2026-04-28",
                lagDays: 0,
                status: "READY",
                note: "facts ready",
              },
            ],
            exceptions: [],
          },
        });
      }
      if (url.includes("/api/v1/wealth/market/turnover")) {
        return responseJson({
          ...turnoverPayload,
          debugInfo: {
            modules: [
              {
                moduleKey: "turnover",
                expectedTradeDate: "2026-04-28",
                observedTradeDate: "2026-04-28",
                lagDays: 0,
                status: "READY",
                note: "facts ready",
              },
            ],
            exceptions: [],
          },
        });
      }
      if (url.includes("/api/v1/wealth/market/leaderboards")) {
        return responseJson({
          ...leaderboardsPayload,
          debugInfo: {
            modules: [
              {
                moduleKey: "leaderboards",
                expectedTradeDate: "2026-04-28",
                observedTradeDate: "2026-04-28",
                lagDays: 0,
                status: "READY",
                note: "facts ready",
              },
            ],
            exceptions: [],
          },
        });
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);
    expect(await screen.findByText("页面调试信息（本地 DEV）")).toBeInTheDocument();
    expect(screen.getByText("marketSummary")).toBeInTheDocument();
    expect(screen.getByText("majorIndices")).toBeInTheDocument();
    expect(screen.getByText("breadth")).toBeInTheDocument();
    expect(screen.getByText("marketStyle")).toBeInTheDocument();
    expect(screen.getByText("turnover")).toBeInTheDocument();
    expect(screen.getByText("leaderboards")).toBeInTheDocument();

    const summaryRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/summary"));
    const majorRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/major-indices"));
    const breadthRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/breadth"));
    const styleRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/style"));
    const turnoverRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/turnover"));
    const leaderboardsRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/leaderboards"));
    const contextRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/context"));
    expect(contextRequest).toBeDefined();
    expect(summaryRequest).toBeDefined();
    expect(majorRequest).toBeDefined();
    expect(breadthRequest).toBeDefined();
    expect(styleRequest).toBeDefined();
    expect(turnoverRequest).toBeDefined();
    expect(leaderboardsRequest).toBeDefined();
    expect(new URL(summaryRequest as string).searchParams.get("debug")).toBe("1");
    expect(new URL(majorRequest as string).searchParams.get("debug")).toBe("1");
    expect(new URL(breadthRequest as string).searchParams.get("debug")).toBe("1");
    expect(new URL(styleRequest as string).searchParams.get("debug")).toBe("1");
    expect(new URL(turnoverRequest as string).searchParams.get("debug")).toBe("1");
    expect(new URL(leaderboardsRequest as string).searchParams.get("debug")).toBe("1");
    expect(new URL(summaryRequest as string).searchParams.get("tradeDate")).toBe("2026-04-28");
    expect(new URL(majorRequest as string).searchParams.get("tradeDate")).toBe("2026-04-28");
    expect(new URL(breadthRequest as string).searchParams.get("tradeDate")).toBe("2026-04-28");
    expect(new URL(styleRequest as string).searchParams.get("tradeDate")).toBe("2026-04-28");
    expect(new URL(turnoverRequest as string).searchParams.get("tradeDate")).toBe("2026-04-28");
    expect(new URL(leaderboardsRequest as string).searchParams.get("tradeDate")).toBe("2026-04-28");
  });
});
