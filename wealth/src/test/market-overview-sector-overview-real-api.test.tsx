import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { marketOverviewModuleSources } from "../features/market-overview/api/moduleSources";
import { MarketOverviewPage } from "../pages/market-overview/MarketOverviewPage";

const sectorColumns = [
  "industryTopGainers",
  "conceptTopGainers",
  "regionTopGainers",
  "fundIn",
  "industryTopLosers",
  "conceptTopLosers",
  "regionTopLosers",
  "fundOut",
].map((columnKey, columnIndex) => ({
  columnKey,
  title: ["行业涨幅前五", "概念涨幅前五", "地域涨幅前五", "资金流入前五", "行业跌幅前五", "概念跌幅前五", "地域跌幅前五", "资金流出前五"][
    columnIndex
  ],
  tone: columnIndex >= 4 ? "DOWN" : "UP",
  metricLabel: columnKey === "fundIn" || columnKey === "fundOut" ? "净流入" : columnIndex >= 4 ? "跌幅" : "涨幅",
  rows: Array.from({ length: 5 }, (_, rowIndex) => ({
    rank: rowIndex + 1,
    subject: {
      subjectType: "sector",
      subjectCode: `${columnKey}-${rowIndex + 1}`,
      subjectName: `${columnIndex + 1}列板块${rowIndex + 1}`,
      sectorType: "INDUSTRY",
    },
    metric: {
      value: columnKey === "fundIn" || columnKey === "fundOut" ? 1000000000 - rowIndex * 100000000 : 5 - rowIndex,
      displayText: columnKey === "fundIn" || columnKey === "fundOut" ? `+${10 - rowIndex}.0亿` : `+${(5 - rowIndex).toFixed(2)}%`,
      unit: columnKey === "fundIn" || columnKey === "fundOut" ? null : "%",
      direction: columnIndex >= 4 ? "DOWN" : "UP",
    },
    leadingStock: null,
  })),
}));

const sectorPayload = {
  tradingDay: {
    tradeDate: "2026-05-11",
    prevTradeDate: "2026-05-08",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: {
    status: "READY",
    displayText: "事实聚合已就绪",
    asOfTime: "2026-05-11T15:05:00+08:00",
  },
  sectorOverview: {
    tradeDate: "2026-05-11",
    status: "READY",
    columns: sectorColumns,
    heatMapItems: Array.from({ length: 20 }, (_, index) => ({
      subject: {
        subjectType: "sector",
        subjectCode: `HM${index + 1}`,
        subjectName: `热力板块${index + 1}`,
        sectorType: index % 3 === 0 ? "INDUSTRY" : index % 3 === 1 ? "CONCEPT" : "REGION",
      },
      changePct: index % 2 === 0 ? 3.2 - index * 0.1 : -2.1 - index * 0.1,
      direction: index % 2 === 0 ? "UP" : "DOWN",
      riseStockCount: 12,
      fallStockCount: 6,
      leadingStock: null,
    })),
  },
  debugInfo: {
    modules: [
      {
        moduleKey: "sectorOverview",
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

function responseJson(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

function maybeContextResponse(url: string): Promise<Response> | null {
  if (!url.includes("/api/v1/wealth/market/context")) {
    return null;
  }
  return Promise.resolve(responseJson(pageContextPayload));
}

describe("market-overview sector-overview real api", () => {
  beforeEach(() => {
    marketOverviewModuleSources.summary = "mock";
    marketOverviewModuleSources.majorIndices = "mock";
    marketOverviewModuleSources.breadth = "mock";
    marketOverviewModuleSources.style = "mock";
    marketOverviewModuleSources.turnover = "mock";
    marketOverviewModuleSources.moneyFlow = "mock";
    marketOverviewModuleSources.leaderboards = "mock";
    marketOverviewModuleSources.limitUp = "mock";
    marketOverviewModuleSources.streakLadder = "mock";
    marketOverviewModuleSources.sectors = "real";
  });

  afterEach(() => {
    Object.assign(marketOverviewModuleSources, moduleSourcesSnapshot);
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.history.pushState({}, "", "/");
  });

  it("renders sector columns and heatmap from the module api without falling back to mock", async () => {
    const requestUrls: string[] = [];
    let resolveSectorFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      requestUrls.push(url);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) {
        return contextResponse;
      }
      if (url.includes("/api/v1/wealth/market/sector-overview")) {
        return new Promise<Response>((resolve) => {
          resolveSectorFetch = resolve;
        });
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);

    const panel = await screen.findByLabelText("板块速览");
    expect(within(panel).getByText("loading")).toBeInTheDocument();
    expect(within(panel).queryByText("半导体")).not.toBeInTheDocument();

    if (typeof resolveSectorFetch !== "function") {
      throw new Error("sector-overview fetch resolver is missing");
    }
    resolveSectorFetch(responseJson(sectorPayload));

    await waitFor(() => {
      expect(within(panel).getByText("行业涨幅前五")).toBeInTheDocument();
    });
    expect(within(panel).getByText("资金流出前五")).toBeInTheDocument();
    expect(within(panel).getByText("1列板块1")).toBeInTheDocument();
    expect(within(panel).getAllByText("+5.00%").length).toBeGreaterThan(0);
    expect(within(panel).getByText("热力板块1")).toBeInTheDocument();
    expect(within(panel).getAllByLabelText(/^板块热力图-/)).toHaveLength(20);

    const sectorRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/sector-overview"));
    expect(sectorRequest).toBeDefined();
    expect(new URL(sectorRequest as string).searchParams.get("market")).toBe("CN_A");
    expect(new URL(sectorRequest as string).searchParams.get("tradeDate")).toBe("2026-05-11");
  });

  it("uses the page-level debug switch for sector-overview", async () => {
    window.history.pushState({}, "", "/market/overview?debug=1");
    const requestUrls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      requestUrls.push(url);
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) {
        return contextResponse;
      }
      if (url.includes("/api/v1/wealth/market/sector-overview")) {
        return responseJson(sectorPayload);
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);

    expect(await screen.findByText("页面调试信息（本地 DEV）")).toBeInTheDocument();
    expect(screen.getByText("sectorOverview")).toBeInTheDocument();
    const sectorRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/sector-overview"));
    expect(sectorRequest).toBeDefined();
    expect(new URL(sectorRequest as string).searchParams.get("debug")).toBe("1");
  });

  it("shows error state when sector-overview request exceeds 5 seconds", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      const contextResponse = maybeContextResponse(url);
      if (contextResponse) {
        return contextResponse;
      }
      if (!url.includes("/api/v1/wealth/market/sector-overview")) {
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

    const panel = rendered.container.querySelector<HTMLElement>('[aria-label="板块速览"]');
    expect(panel).not.toBeNull();
    if (!panel) {
      throw new Error("sector-overview panel not found");
    }
    expect(within(panel).getByText("loading")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(panel).getByText("请求超时：/api/v1/wealth/market/sector-overview")).toBeInTheDocument();
    expect(within(panel).getByText("error")).toBeInTheDocument();
  }, 15000);
});
