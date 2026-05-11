import { act, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { marketOverviewModuleSources } from "../features/market-overview/api/moduleSources";
import { MarketOverviewPage } from "../pages/market-overview/MarketOverviewPage";

const moneyFlowPayload = {
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
  moneyFlow: {
    tradeDate: "2026-05-11",
    metrics: {
      todayNetAmount: -27004993536,
      prevNetAmount: -55190130688,
      unit: "yuan",
    },
    byOrderSize: {
      elg: { amount: -8282591232, rate: -0.23 },
      lg: { amount: -18722402304, rate: -0.53 },
      md: { amount: -5500018688, rate: -0.16 },
      sm: { amount: 32505012224, rate: 0.92 },
    },
    historyByRange: {
      oneMonth: [
        { tradeDate: "2026-05-08", netAmount: -55190130688 },
        { tradeDate: "2026-05-11", netAmount: -27004993536 },
      ],
      threeMonth: [
        { tradeDate: "2026-04-01", netAmount: 12600000000 },
        { tradeDate: "2026-05-11", netAmount: -27004993536 },
      ],
    },
  },
  debugInfo: {
    modules: [
      {
        moduleKey: "moneyFlow",
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

function responseJson(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

describe("market-overview money-flow real api", () => {
  beforeEach(() => {
    marketOverviewModuleSources.summary = "mock";
    marketOverviewModuleSources.majorIndices = "mock";
    marketOverviewModuleSources.breadth = "mock";
    marketOverviewModuleSources.style = "mock";
    marketOverviewModuleSources.turnover = "mock";
    marketOverviewModuleSources.moneyFlow = "real";
    marketOverviewModuleSources.leaderboards = "mock";
    marketOverviewModuleSources.limitUp = "mock";
    marketOverviewModuleSources.sectors = "mock";
  });

  afterEach(() => {
    Object.assign(marketOverviewModuleSources, moduleSourcesSnapshot);
    vi.restoreAllMocks();
    vi.useRealTimers();
    window.history.pushState({}, "", "/");
  });

  it("renders money-flow values from the module api without falling back to mock", async () => {
    const requestUrls: string[] = [];
    let resolveMoneyFlowFetch: ((value: Response | PromiseLike<Response>) => void) | undefined;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      requestUrls.push(url);
      if (url.includes("/api/v1/wealth/market/money-flow")) {
        return new Promise<Response>((resolve) => {
          resolveMoneyFlowFetch = resolve;
        });
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);

    const panel = await screen.findByLabelText("大盘资金流向");
    expect(within(panel).getByText("loading")).toBeInTheDocument();
    expect(within(panel).queryByText("+186.4亿")).not.toBeInTheDocument();

    if (typeof resolveMoneyFlowFetch !== "function") {
      throw new Error("money-flow fetch resolver is missing");
    }
    resolveMoneyFlowFetch(responseJson(moneyFlowPayload));

    await waitFor(() => {
      expect(within(panel).getByText("-270.0亿")).toBeInTheDocument();
    });
    expect(within(panel).getByText("-551.9亿")).toBeInTheDocument();
    expect(within(panel).getByText("超大单 -82.8亿")).toBeInTheDocument();
    expect(within(panel).getByText("大单 -187.2亿")).toBeInTheDocument();
    expect(within(panel).getByText("中单 -55.0亿")).toBeInTheDocument();
    expect(within(panel).getByText("小单 +325.1亿")).toBeInTheDocument();

    const moneyFlowRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/money-flow"));
    expect(moneyFlowRequest).toBeDefined();
    expect(new URL(moneyFlowRequest as string).searchParams.get("market")).toBe("CN_A");
  });

  it("uses the page-level debug switch for money-flow", async () => {
    window.history.pushState({}, "", "/market/overview?debug=1");
    const requestUrls: string[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      requestUrls.push(url);
      if (url.includes("/api/v1/wealth/market/money-flow")) {
        return responseJson(moneyFlowPayload);
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);

    expect(await screen.findByText("页面调试信息（本地 DEV）")).toBeInTheDocument();
    expect(screen.getByText("moneyFlow")).toBeInTheDocument();
    const moneyFlowRequest = requestUrls.find((url) => url.includes("/api/v1/wealth/market/money-flow"));
    expect(moneyFlowRequest).toBeDefined();
    expect(new URL(moneyFlowRequest as string).searchParams.get("debug")).toBe("1");
  });

  it("shows error state when money-flow request exceeds 5 seconds", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (!url.includes("/api/v1/wealth/market/money-flow")) {
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

    const panel = rendered.container.querySelector<HTMLElement>('[aria-label="大盘资金流向"]');
    expect(panel).not.toBeNull();
    if (!panel) {
      throw new Error("money-flow panel not found");
    }
    expect(within(panel).getByText("loading")).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
      await Promise.resolve();
    });
    expect(within(panel).getByText("请求超时：/api/v1/wealth/market/money-flow")).toBeInTheDocument();
    expect(within(panel).getByText("error")).toBeInTheDocument();
  }, 15000);
});
