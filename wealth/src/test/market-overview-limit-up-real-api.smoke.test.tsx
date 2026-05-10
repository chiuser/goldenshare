import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { marketOverviewModuleSources } from "../features/market-overview/api/moduleSources";
import { MarketOverviewPage } from "../pages/market-overview/MarketOverviewPage";

const limitUpSuccessPayload = {
  tradingDay: {
    tradeDate: "2026-04-28",
    prevTradeDate: "2026-04-27",
    market: "CN_A",
    isTradingDay: true,
    sessionStatus: "CLOSED",
    timezone: "Asia/Shanghai",
  },
  pageStatus: {
    status: "PARTIAL",
    displayText: "部分模块延迟",
    asOfTime: "2026-04-28T15:05:00+08:00",
  },
  limitUp: {
    tradeDate: "2026-04-28",
    summaryCards: [
      { key: "limitUpCount", label: "涨停家数", value: "59/8", direction: "UP", subText: "总涨停家数/ST涨停家数" },
      { key: "limitDownCount", label: "跌停家数", value: "7/1", direction: "DOWN", subText: "总跌停家数/ST跌停家数" },
      { key: "brokenLimitCount", label: "炸板家数", value: "21/2", direction: "FLAT", subText: "总炸板家数/ST炸板家数" },
      { key: "sealingRate", label: "封板率", value: 66.7, unit: "%", direction: "UP", subText: "非ST口径" },
      { key: "streakCount", label: "连板家数", value: 19, unit: "只", direction: "UP", subText: "二板及以上" },
      { key: "maxBoard", label: "最高连板", value: 7, unit: "板", direction: "UP", subText: "五板及以上合并展示" },
      { key: "skyToFloorCount", label: "天地板", value: 2, unit: "只", direction: "DOWN", subText: "高风险结构" },
      { key: "floorToSkyCount", label: "地天板", value: 1, unit: "只", direction: "UP", subText: "反包结构" },
    ],
    todayStructure: {
      tradeDate: "2026-04-28",
      selectedSectorCode: "BK1001",
      selectedStockCode: "000001.SZ",
      sectors: [
        { sectorCode: "BK1001", sectorName: "机器人", sectorType: "CONCEPT", limitUpCount: 12 },
        { sectorCode: "BK1002", sectorName: "固态电池", sectorType: "CONCEPT", limitUpCount: 8 },
      ],
      leaderStocks: {
        BK1001: [
          {
            stockCode: "000001.SZ",
            stockName: "示例个股A",
            latestPrice: 10.32,
            changePct: 10.01,
            rank: 1,
            streakLabel: "3连板",
            recentLimitText: "10天4板",
            firstLimitTime: "09:40:00",
            openTimes: 1,
            sealedAmountDisplayText: "2.6亿",
          },
        ],
      },
    },
    yesterdayStructure: {
      tradeDate: "2026-04-27",
      selectedSectorCode: "BK1002",
      selectedStockCode: "000002.SZ",
      sectors: [{ sectorCode: "BK1002", sectorName: "固态电池", sectorType: "CONCEPT", limitUpCount: 9 }],
      leaderStocks: {
        BK1002: [
          {
            stockCode: "000002.SZ",
            stockName: "示例个股B",
            latestPrice: 8.16,
            changePct: 9.99,
            rank: 1,
            streakLabel: "2连板",
            recentLimitText: "5天2板",
            firstLimitTime: "10:10:00",
            openTimes: 0,
            sealedAmountDisplayText: "1.4亿",
          },
        ],
      },
    },
    historyPoints: {
      oneMonth: [
        { tradeDate: "2026-04-27", limitUpCount: 53, limitDownCount: 6 },
        { tradeDate: "2026-04-28", limitUpCount: 59, limitDownCount: 7 },
      ],
      threeMonth: [
        { tradeDate: "2026-03-03", limitUpCount: 34, limitDownCount: 11 },
        { tradeDate: "2026-04-28", limitUpCount: 59, limitDownCount: 7 },
      ],
    },
  },
};

const moduleSourcesSnapshot = { ...marketOverviewModuleSources };

function responseJson(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

describe("market-overview limit-up real api smoke", () => {
  beforeEach(() => {
    marketOverviewModuleSources.summary = "mock";
    marketOverviewModuleSources.majorIndices = "mock";
    marketOverviewModuleSources.breadth = "mock";
    marketOverviewModuleSources.style = "mock";
    marketOverviewModuleSources.turnover = "mock";
    marketOverviewModuleSources.moneyFlow = "mock";
    marketOverviewModuleSources.leaderboards = "mock";
    marketOverviewModuleSources.limitUp = "real";
    marketOverviewModuleSources.sectors = "mock";
  });

  afterEach(() => {
    Object.assign(marketOverviewModuleSources, moduleSourcesSnapshot);
    vi.restoreAllMocks();
  });

  it("renders-limit-up-panel", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
      if (url.includes("/api/v1/wealth/market/limit-up/summary")) {
        return responseJson(limitUpSuccessPayload);
      }
      throw new Error(`unexpected url: ${url}`);
    });

    render(<MarketOverviewPage />);

    const panel = await screen.findByLabelText("涨跌停统计与分布");
    await waitFor(() => {
      expect(within(panel).queryByText("loading")).not.toBeInTheDocument();
    });
    expect(within(panel).getByText("涨停家数")).toBeInTheDocument();
    expect(within(panel).getByText("59/8")).toBeInTheDocument();
    expect(within(panel).getByText("部分模块延迟")).toBeInTheDocument();
    expect(within(panel).getByText("机器人")).toBeInTheDocument();
  });

  it("shows-partial-and-error-state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce({
      ok: false,
      json: async () => ({ code: "503001", message: "limit_up unavailable" }),
      status: 503,
    } as Response);

    render(<MarketOverviewPage />);

    const panel = await screen.findByLabelText("涨跌停统计与分布");
    await waitFor(() => {
      expect(within(panel).getByText("error")).toBeInTheDocument();
    });
    expect(within(panel).getByText("limit_up unavailable")).toBeInTheDocument();
  });
});
