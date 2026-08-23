import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { marketOverviewModuleSources } from "../features/market-overview/api/moduleSources";
import { MarketOverviewPage } from "../pages/market-overview/MarketOverviewPage";

const moduleSourcesSnapshot = { ...marketOverviewModuleSources };

const pageContextPayload = {
  pageContext: {
    market: "CN_A",
    tradeDate: "2026-05-11",
    prevTradeDate: "2026-05-08",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
    generatedAt: "2026-05-11T15:05:00+08:00",
    source: "default",
  },
};

const newsBriefsPayload = {
  newsWindow: {
    market: "CN_A",
    startAt: "2026-05-10T00:00:00+08:00",
    endAt: "2026-05-11T15:05:00+08:00",
    timezone: "Asia/Shanghai",
  },
  pageStatus: { status: "READY", displayText: "新闻速览已就绪", asOfTime: "2026-05-11T15:05:00+08:00" },
  newsBriefs: {
    windowStartAt: "2026-05-10T00:00:00+08:00",
    windowEndAt: "2026-05-11T15:05:00+08:00",
    panelKey: "newsBriefs",
    visibleItemCount: 10,
    updatedAt: "2026-05-11T15:05:00+08:00",
    sortRule: "publishTime_desc_priority_desc",
    clickablePolicy: "reader",
    items: [
      {
        newsId: "market-1",
        publishTime: "2026-05-11T10:01:02",
        displayTime: "05-11 10:01:02",
        title: "宏观政策保持连续性",
        category: "market",
        source: "Tushare",
        subject: null,
        priority: null,
        readerMode: "TEXT",
        clickable: true,
      },
    ],
  },
  debugInfo: {
    modules: [
      {
        moduleKey: "newsBriefs",
        expectedTradeDate: "2026-05-11",
        observedTradeDate: "2026-05-11",
        lagDays: 0,
        status: "READY",
        note: "facts ready",
      },
    ],
    exceptions: [],
  },
};

const stockNewsPayload = {
  newsWindow: newsBriefsPayload.newsWindow,
  pageStatus: { status: "READY", displayText: "个股新闻已就绪", asOfTime: "2026-05-11T15:05:00+08:00" },
  stockNews: {
    windowStartAt: "2026-05-10T00:00:00+08:00",
    windowEndAt: "2026-05-11T15:05:00+08:00",
    panelKey: "stockNews",
    visibleItemCount: 10,
    updatedAt: "2026-05-11T15:05:00+08:00",
    sortRule: "publishTime_desc_priority_desc",
    clickablePolicy: "reader",
    items: [
      {
        newsId: "stock-1",
        publishTime: "2026-05-11T09:31:10",
        displayTime: "05-11 09:31:10",
        title: "公司公告披露一季度经营情况",
        category: "stock",
        source: "Tushare",
        subject: null,
        priority: null,
        readerMode: "TEXT",
        clickable: true,
      },
    ],
  },
  debugInfo: {
    modules: [
      {
        moduleKey: "stockNews",
        expectedTradeDate: "2026-05-11",
        observedTradeDate: "2026-05-11",
        lagDays: 0,
        status: "READY",
        note: "facts ready",
      },
    ],
    exceptions: [],
  },
};

const refreshedNewsBriefsPayload = {
  ...newsBriefsPayload,
  pageStatus: { status: "READY", displayText: "新闻速览已刷新", asOfTime: "2026-05-11T15:15:00+08:00" },
  newsBriefs: {
    ...newsBriefsPayload.newsBriefs,
    updatedAt: "2026-05-11T15:15:00+08:00",
    items: [
      {
        ...newsBriefsPayload.newsBriefs.items[0],
        newsId: "market-2",
        displayTime: "05-11 15:15:00",
        title: "最新宏观新闻滚动展示",
      },
    ],
  },
};

const refreshedStockNewsPayload = {
  ...stockNewsPayload,
  pageStatus: { status: "READY", displayText: "个股新闻已刷新", asOfTime: "2026-05-11T15:15:00+08:00" },
  stockNews: {
    ...stockNewsPayload.stockNews,
    updatedAt: "2026-05-11T15:15:00+08:00",
    items: [
      {
        ...stockNewsPayload.stockNews.items[0],
        newsId: "stock-2",
        displayTime: "05-11 15:15:00",
        title: "最新公司新闻滚动展示",
      },
    ],
  },
};

function responseJson(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

function urlString(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

function maybeContextResponse(url: string): Promise<Response> | null {
  if (!url.includes("/api/v1/wealth/market/context")) return null;
  return Promise.resolve(responseJson(pageContextPayload));
}

describe("market-overview news real api", () => {
  beforeEach(() => {
    marketOverviewModuleSources.summary = "mock";
    marketOverviewModuleSources.majorIndices = "mock";
    marketOverviewModuleSources.breadth = "mock";
    marketOverviewModuleSources.style = "mock";
    marketOverviewModuleSources.turnover = "mock";
    marketOverviewModuleSources.moneyFlow = "mock";
    marketOverviewModuleSources.news = "real";
    marketOverviewModuleSources.leaderboards = "mock";
    marketOverviewModuleSources.limitUp = "mock";
    marketOverviewModuleSources.streakLadder = "mock";
    marketOverviewModuleSources.sectors = "mock";
  });

  afterEach(() => {
    Object.assign(marketOverviewModuleSources, moduleSourcesSnapshot);
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.history.pushState({}, "", "/");
  });

  it("renders news briefs and stock news from independent module APIs", async () => {
    const requestUrls: string[] = [];
    let resolveBriefsFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    let resolveStocksFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlString(input);
      requestUrls.push(url);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/news/briefs")) {
        return new Promise<Response>((resolve) => {
          resolveBriefsFetch = resolve;
        });
      }
      if (url.includes("/api/v1/wealth/market/news/stocks")) {
        return new Promise<Response>((resolve) => {
          resolveStocksFetch = resolve;
        });
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);

    const newsPanel = await screen.findByLabelText("新闻速览");
    const stockPanel = await screen.findByLabelText("个股新闻");
    expect(within(newsPanel).getByText("loading")).toBeInTheDocument();
    expect(within(stockPanel).getByText("loading")).toBeInTheDocument();

    if (typeof resolveBriefsFetch !== "function" || typeof resolveStocksFetch !== "function") {
      throw new Error("news fetch resolvers are missing");
    }
    resolveBriefsFetch(responseJson(newsBriefsPayload));
    resolveStocksFetch(responseJson(stockNewsPayload));

    await waitFor(() => {
      expect(within(newsPanel).getByText("宏观政策保持连续性")).toBeInTheDocument();
      expect(within(stockPanel).getByText("公司公告披露一季度经营情况")).toBeInTheDocument();
    });
    expect(within(newsPanel).getByText("05-11 10:01:02")).toBeInTheDocument();
    expect(within(stockPanel).getByText("05-11 09:31:10")).toBeInTheDocument();
    expect(newsPanel.querySelectorAll("a")).toHaveLength(0);
    expect(stockPanel.querySelectorAll("a")).toHaveLength(0);

    const briefsRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/news/briefs"));
    const stocksRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/news/stocks"));
    expect(briefsRequest).toBeDefined();
    expect(stocksRequest).toBeDefined();
    expect(new URL(briefsRequest as string).searchParams.has("tradeDate")).toBe(false);
    expect(new URL(stocksRequest as string).searchParams.has("tradeDate")).toBe(false);
  });

  it("uses page-level debug switch for both news endpoints", async () => {
    window.history.pushState({}, "", "/market/overview?debug=1");
    const requestUrls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlString(input);
      requestUrls.push(url);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/news/briefs")) return responseJson(newsBriefsPayload);
      if (url.includes("/api/v1/wealth/market/news/stocks")) return responseJson(stockNewsPayload);
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);

    expect(await screen.findByText("页面调试信息（本地 DEV）")).toBeInTheDocument();
    expect(screen.getByText("newsBriefs")).toBeInTheDocument();
    expect(screen.getByText("stockNews")).toBeInTheDocument();
    const briefsRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/news/briefs"));
    const stocksRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/news/stocks"));
    expect(new URL(briefsRequest as string).searchParams.get("debug")).toBe("1");
    expect(new URL(stocksRequest as string).searchParams.get("debug")).toBe("1");
  });

  it("shows independent error states when news requests exceed 5 seconds", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = urlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (!url.includes("/api/v1/wealth/market/news/briefs") && !url.includes("/api/v1/wealth/market/news/stocks")) {
        return Promise.reject(new Error(`unexpected url: ${url}`));
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

    const newsPanel = rendered.container.querySelector<HTMLElement>('[aria-label="新闻速览"]');
    const stockPanel = rendered.container.querySelector<HTMLElement>('[aria-label="个股新闻"]');
    expect(newsPanel).not.toBeNull();
    expect(stockPanel).not.toBeNull();
    if (!newsPanel || !stockPanel) {
      throw new Error("news panels are missing");
    }
    expect(within(newsPanel).getByText("loading")).toBeInTheDocument();
    expect(within(stockPanel).getByText("loading")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(newsPanel).getByText("请求超时：/api/v1/wealth/market/news/briefs")).toBeInTheDocument();
    expect(within(stockPanel).getByText("请求超时：/api/v1/wealth/market/news/stocks")).toBeInTheDocument();
    expect(within(newsPanel).getByText("error")).toBeInTheDocument();
    expect(within(stockPanel).getByText("error")).toBeInTheDocument();
  }, 15000);

  it("refreshes news panels every 10 minutes without clearing existing items", async () => {
    vi.useFakeTimers();
    let briefsCalls = 0;
    let stocksCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/news/briefs")) {
        briefsCalls += 1;
        return responseJson(briefsCalls === 1 ? newsBriefsPayload : refreshedNewsBriefsPayload);
      }
      if (url.includes("/api/v1/wealth/market/news/stocks")) {
        stocksCalls += 1;
        return responseJson(stocksCalls === 1 ? stockNewsPayload : refreshedStockNewsPayload);
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const newsPanel = screen.getByLabelText("新闻速览");
    const stockPanel = screen.getByLabelText("个股新闻");
    expect(within(newsPanel).getByText("宏观政策保持连续性")).toBeInTheDocument();
    expect(within(stockPanel).getByText("公司公告披露一季度经营情况")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
      await Promise.resolve();
    });

    expect(within(newsPanel).getByText("最新宏观新闻滚动展示")).toBeInTheDocument();
    expect(within(stockPanel).getByText("最新公司新闻滚动展示")).toBeInTheDocument();
    expect(within(newsPanel).queryByText("loading")).not.toBeInTheDocument();
    expect(within(stockPanel).queryByText("loading")).not.toBeInTheDocument();
    expect(briefsCalls).toBe(2);
    expect(stocksCalls).toBe(2);
  });

  it("opens one reader from either panel and keeps its content through list refresh", async () => {
    vi.useFakeTimers();
    let briefsCalls = 0;
    let stocksCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/news/items/market-1")) {
        return responseJson({
          newsId: "market-1",
          title: "宏观政策保持连续性",
          source: "Tushare",
          publishTime: newsBriefsPayload.newsBriefs.items[0].publishTime,
          readerMode: "TEXT",
          url: null,
          html: null,
          content: "阅读器中的完整新闻正文",
        });
      }
      if (url.includes("/api/v1/wealth/market/news/briefs")) {
        briefsCalls += 1;
        return responseJson(briefsCalls === 1 ? newsBriefsPayload : refreshedNewsBriefsPayload);
      }
      if (url.includes("/api/v1/wealth/market/news/stocks")) {
        stocksCalls += 1;
        return responseJson(stocksCalls === 1 ? stockNewsPayload : refreshedStockNewsPayload);
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const newsPanel = screen.getByLabelText("新闻速览");
    const stockPanel = screen.getByLabelText("个股新闻");
    const marketTrigger = within(newsPanel).getByRole("button", { name: /宏观政策保持连续性/ });
    const stockTrigger = within(stockPanel).getByRole("button", { name: /公司公告披露一季度经营情况/ });
    expect(marketTrigger).toHaveAttribute("aria-haspopup", "dialog");
    expect(stockTrigger).toHaveAttribute("aria-haspopup", "dialog");

    fireEvent.click(marketTrigger);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByText("阅读器中的完整新闻正文")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
      await Promise.resolve();
    });
    expect(within(newsPanel).getByText("最新宏观新闻滚动展示")).toBeInTheDocument();
    expect(screen.getByText("阅读器中的完整新闻正文")).toBeInTheDocument();
    expect(screen.getAllByRole("dialog")).toHaveLength(1);
  });

  it("keeps current news visible when a background refresh fails", async () => {
    vi.useFakeTimers();
    let briefsCalls = 0;
    let stocksCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = urlString(input);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) return contextResponse;
      if (url.includes("/api/v1/wealth/market/news/briefs")) {
        briefsCalls += 1;
        if (briefsCalls === 1) return responseJson(newsBriefsPayload);
        throw new Error("briefs refresh failed");
      }
      if (url.includes("/api/v1/wealth/market/news/stocks")) {
        stocksCalls += 1;
        if (stocksCalls === 1) return responseJson(stockNewsPayload);
        throw new Error("stocks refresh failed");
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    const newsPanel = screen.getByLabelText("新闻速览");
    const stockPanel = screen.getByLabelText("个股新闻");
    expect(within(newsPanel).getByText("宏观政策保持连续性")).toBeInTheDocument();
    expect(within(stockPanel).getByText("公司公告披露一季度经营情况")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
      await Promise.resolve();
    });

    expect(within(newsPanel).getByText("宏观政策保持连续性")).toBeInTheDocument();
    expect(within(stockPanel).getByText("公司公告披露一季度经营情况")).toBeInTheDocument();
    expect(within(newsPanel).queryByText("error")).not.toBeInTheDocument();
    expect(within(stockPanel).queryByText("error")).not.toBeInTheDocument();
    expect(briefsCalls).toBe(2);
    expect(stocksCalls).toBe(2);
  });
});
