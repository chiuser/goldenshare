import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { marketOverviewModuleSources } from "../features/market-overview/api/moduleSources";
import { MarketOverviewPage } from "../pages/market-overview/MarketOverviewPage";

const streakLadderSuccessPayload = {
  tradingDay: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: {
    status: "READY",
    displayText: "事实聚合已就绪",
    asOfTime: "2026-04-28T15:05:00+08:00",
  },
  streakLadderV5: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    highestStreakLevel: 5,
    aboveFive: [],
    promotions: {
      4: {
        previousLabel: "昨日3板",
        currentLabel: "今日4板",
        previousStocks: [
          {
            stockName: "示例昨日股票A",
            stockCode: "000001.SZ",
            latestPrice: 12.34,
            changePct: 10.02,
            sectorName: "机器人",
            openTimes: 0,
            firstLimitTime: "92500",
            currentStreakLevel: 3,
            advanced: false,
          },
        ],
        currentStocks: [
          {
            stockName: "示例晋级股票A",
            stockCode: "000002.SZ",
            latestPrice: 15.8,
            changePct: 10.0,
            sectorName: "机器人",
            openTimes: 1,
            currentStreakLevel: 4,
            advanced: true,
          },
        ],
      },
    },
    firstBoard: [
      {
        stockName: "示例首板A",
        stockCode: "000003.SZ",
        latestPrice: 9.56,
        changePct: 10.01,
        sectorName: "算力设备",
        openTimes: 2,
        currentStreakLevel: 1,
        advanced: false,
      },
    ],
  },
};

const moduleSourcesSnapshot = { ...marketOverviewModuleSources };

function responseJson(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

describe("market-overview streak-ladder real api smoke", () => {
  beforeEach(() => {
    marketOverviewModuleSources.summary = "mock";
    marketOverviewModuleSources.majorIndices = "mock";
    marketOverviewModuleSources.breadth = "mock";
    marketOverviewModuleSources.style = "mock";
    marketOverviewModuleSources.turnover = "mock";
    marketOverviewModuleSources.moneyFlow = "mock";
    marketOverviewModuleSources.leaderboards = "mock";
    marketOverviewModuleSources.limitUp = "mock";
    marketOverviewModuleSources.streakLadder = "real";
    marketOverviewModuleSources.sectors = "mock";
  });

  afterEach(() => {
    Object.assign(marketOverviewModuleSources, moduleSourcesSnapshot);
    vi.restoreAllMocks();
  });

  it("renders-streak-ladder-panel", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/api/v1/wealth/market/streak-ladder")) {
        return responseJson(streakLadderSuccessPayload);
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);

    const panel = await screen.findByLabelText("连板天梯");
    await waitFor(() => {
      expect(within(panel).queryByText("loading")).not.toBeInTheDocument();
    });
    expect(within(panel).getByText("昨日3板 → 今日4板")).toBeInTheDocument();
    expect(within(panel).getByText("示例晋级股票A")).toBeInTheDocument();
    expect(within(panel).getByText("示例首板A")).toBeInTheDocument();
  });

  it("shows-error-state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      json: async () => ({ code: "503001", message: "streak ladder unavailable" }),
      status: 503,
    } as Response);

    render(<MarketOverviewPage />);

    const panel = await screen.findByLabelText("连板天梯");
    await waitFor(() => {
      expect(within(panel).queryByText("loading")).not.toBeInTheDocument();
    });
    expect(within(panel).getByText("streak ladder unavailable")).toBeInTheDocument();
  });

  it("collapses-first-board-to-two-rows-and-expands-on-click", async () => {
    const payload = {
      ...streakLadderSuccessPayload,
      streakLadderV5: {
        ...streakLadderSuccessPayload.streakLadderV5,
        highestStreakLevel: 1,
        promotions: {},
        firstBoard: Array.from({ length: 13 }, (_, index) => ({
          stockName: `首板示例${index + 1}`,
          stockCode: `0000${index + 1}.SZ`,
          latestPrice: 10 + index,
          changePct: 10.0,
          sectorName: "示例板块",
          openTimes: index === 0 ? 0 : 1,
          firstLimitTime: index === 0 ? "92500" : "100000",
          currentStreakLevel: 1,
          advanced: true,
        })),
      },
    };

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/api/v1/wealth/market/streak-ladder")) {
        return responseJson(payload);
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);

    const panel = await screen.findByLabelText("连板天梯");
    await waitFor(() => {
      expect(within(panel).queryByText("loading")).not.toBeInTheDocument();
    });

    const firstLayer = panel.querySelector<HTMLElement>('section[data-layer-key="first"]');
    expect(firstLayer).not.toBeNull();
    if (!firstLayer) throw new Error("first layer not found");

    expect(within(firstLayer).queryAllByText("一字板").length).toBeGreaterThan(0);
    expect(firstLayer.querySelectorAll(".stock-compact-card-v5")).toHaveLength(12);
    expect(within(firstLayer).queryByText("首板示例13")).not.toBeInTheDocument();

    fireEvent.click(within(firstLayer).getByRole("button", { name: "展开全部" }));

    await waitFor(() => {
      expect(firstLayer.querySelectorAll(".stock-compact-card-v5")).toHaveLength(13);
    });
    expect(within(firstLayer).getByText("首板示例13")).toBeInTheDocument();
  });
});
