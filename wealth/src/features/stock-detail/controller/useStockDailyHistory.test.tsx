import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type { DetailChartHistoryViewport } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { fetchStockNineTurnSeries } from "../../nine-turn/api/nineTurnApiClient";
import type { NineTurnMarkerDto, NineTurnSeriesDto } from "../../nine-turn/api/nineTurnApiTypes";
import { fetchStockDetailKline } from "../api/stockDetailApiClient";
import type { StockDetailKlineResponseDto, StockKlineBarDto } from "../api/stockDetailApiTypes";
import { toCandlePoint } from "../api/stockDetailViewModelAdapter";
import { fetchStockTrendChannel } from "../trend-channel/api/stockTrendChannelApiClient";
import type { StockTrendChannelResponseDto } from "../trend-channel/api/stockTrendChannelApiTypes";
import { useStockDailyHistory } from "./useStockDailyHistory";

vi.mock("../api/stockDetailApiClient");
vi.mock("../../nine-turn/api/nineTurnApiClient");
vi.mock("../trend-channel/api/stockTrendChannelApiClient");

const code = "600519.SH";
const anchor = "2026-11-19";
const end = "2024-10-29";
const start = "2024-10-28";
const first = "2024-10-30";

function bar(tradeDate: string): StockKlineBarDto {
  return {
    tradeDate, open: 10, high: 11, low: 9, close: 10.5, volDisplay: "100",
    factors: { ma: { ma5: 10 }, boll: {}, macd: {}, kdj: {} },
  };
}

const seed = {
  tsCode: code, tradeDate: anchor, nextEndDate: end, supportsNineTurn: true,
  candles: [bar(first), bar(anchor)].map(toCandlePoint),
};

function kline(): StockDetailKlineResponseDto {
  return {
    pageContext: {
      tradeDate: end, market: "CN_A", isTradingDay: true, sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai", generatedAt: "2026-11-20T10:00:00+08:00", source: "explicit",
    },
    stockRef: { tsCode: code }, period: "day", adjustment: "forward", sourceAdjustment: "qfq",
    bars: [bar(start), bar(end)], meta: { count: 2, limit: 500, endDate: end, nextEndDate: null },
    dataStatus: { status: "READY", expectedTradeDate: end, observedTradeDate: end },
  };
}

function nineTurn(): NineTurnSeriesDto {
  const marker: NineTurnMarkerDto =
    { tradeDate: start, tradeTime: null, direction: "UP", sequenceNumber: 1, completed: false };
  return {
    dataStatus: { code: null, expectedEndDate: end, message: null, observedEndDate: end, status: "READY" },
    debugInfo: null, latestMarker: marker, markers: [marker], tsCode: code, period: "day", subjectType: "stock",
    meta: {
      startDate: start, endDate: end, limit: 500, comparisonLag: 4, signalThreshold: 9, formulaVersion: 1,
      sourceRowCount: 2, markerCount: 1, matchedRowCount: 2, missingRowCount: 0, hasMore: false,
      nextCursor: null, observedStartDate: start, observedEndDate: end,
    },
  };
}

function trend(): StockTrendChannelResponseDto {
  const band = { lower: 9, upper: 11, position: "INSIDE", state: "UP" } as const;
  return {
    stockRef: { tsCode: code }, period: "day", adjustment: "forward", sourceAdjustment: "qfq",
    bars: ["2024-10-25", end].map(tradeDate => ({
      tradeDate, open: 10, high: 11, low: 9, close: 10.5, shortChannel: band, longChannel: band, combinedState: "UP_UP",
    })),
    formula: {
      key: "high-low-ema-hysteresis", version: "stock-daily-trend-channel-v1", shortPeriod: 25,
      longPeriod: 90, seed: "first_observation", stateRule: "strict_close_breakout_inside_retention",
    },
    meta: { count: 2, limit: 2, endDate: end }, dataStatus: { status: "READY" },
  };
}

function viewport(overrides: Partial<DetailChartHistoryViewport> = {}): DetailChartHistoryViewport {
  return { firstDate: first, leftDate: first, remaining: 1, direction: "history", beyondLeft: true,
    gesture: Symbol(), ...overrides };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchStockDetailKline).mockResolvedValue(kline());
  vi.mocked(fetchStockNineTurnSeries).mockResolvedValue(nineTurn());
  vi.mocked(fetchStockTrendChannel).mockResolvedValue(trend());
});

it("prepends one older page, loads layers for its dates and retries only the failed layer", async () => {
  vi.mocked(fetchStockTrendChannel).mockRejectedValueOnce(new Error("trend failed"));
  const { result } = renderHook(() => useStockDailyHistory(seed, true));
  act(() => {
    result.current.onViewport(viewport({ direction: "stationary" }));
    result.current.onViewport(viewport({ remaining: 101 }));
  });
  expect(fetchStockDetailKline).not.toHaveBeenCalled();
  act(() => {
    result.current.onViewport(viewport({ remaining: 100 }));
    result.current.onViewport(viewport());
  });
  await waitFor(() => expect(result.current.visible?.pages[0]?.nineTurn?.phase).toBe("ready"));
  expect(fetchStockDetailKline).toHaveBeenCalledExactlyOnceWith(
    expect.objectContaining({ tsCode: code, tradeDate: anchor, endDate: end, limit: 500 }), expect.anything(),
  );
  expect(fetchStockNineTurnSeries).toHaveBeenCalledExactlyOnceWith(
    { tsCode: code, startDate: start, endDate: end, limit: 500, period: "day" }, expect.anything(),
  );
  expect(result.current.visible?.candles.map(candle => candle.fullDate)).toEqual([start, end, first, anchor]);
  expect(fetchStockTrendChannel).not.toHaveBeenCalled();
  act(() => result.current.ensureTrend());
  await waitFor(() => expect(result.current.visible?.pages[0]?.trend?.phase).toBe("error"));
  act(() => result.current.retryLayer(result.current.visible!.pages[0]!, "trend"));
  await waitFor(() => expect(result.current.visible?.pages[0]?.trend).toEqual(
    { phase: "ready", points: [expect.objectContaining({ time: end })] },
  ));
  expect(fetchStockTrendChannel).toHaveBeenCalledTimes(2);
  expect(fetchStockTrendChannel).toHaveBeenLastCalledWith({ tsCode: code, endDate: end, limit: 2 }, expect.anything());
  act(() => result.current.onViewport(viewport({ firstDate: start })));
  expect(fetchStockDetailKline).toHaveBeenCalledTimes(1);
  expect(fetchStockNineTurnSeries).toHaveBeenCalledTimes(1);
});

it("retries the same end date only from a new drag after a failed page", async () => {
  vi.mocked(fetchStockDetailKline).mockRejectedValueOnce(new Error("kline failed"));
  const { result } = renderHook(() => useStockDailyHistory(seed, true));
  const gesture = viewport();
  act(() => result.current.onViewport(gesture));
  await waitFor(() => expect(result.current.visible?.phase).toBe("error"));
  expect(result.current.visible?.candles).toEqual(seed.candles);
  act(() => result.current.onViewport(gesture));
  expect(fetchStockDetailKline).toHaveBeenCalledTimes(1);
  act(() => result.current.onViewport(viewport()));
  await waitFor(() => expect(result.current.visible?.candles.length).toBe(4));
  expect(fetchStockDetailKline).toHaveBeenLastCalledWith(expect.objectContaining({ endDate: end }), expect.anything());
});

it.each([
  ["changing the stock", { historySeed: { ...seed, tsCode: "000001.SZ" }, daily: true }],
  ["changing the page date", { historySeed: { ...seed, tradeDate: "2026-11-18" }, daily: true }],
  ["leaving daily", { historySeed: seed, daily: false }],
] as const)("discards a late page after %s", async (_reason, nextProps) => {
  let finish!: (response: StockDetailKlineResponseDto) => void;
  vi.mocked(fetchStockDetailKline).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
  const { result, rerender } = renderHook(({ historySeed, daily }) => useStockDailyHistory(historySeed, daily),
    { initialProps: { historySeed: seed, daily: true } });
  act(() => result.current.onViewport(viewport()));
  const signal = vi.mocked(fetchStockDetailKline).mock.calls[0]?.[1]?.signal;
  rerender(nextProps);
  expect(signal?.aborted).toBe(true);
  await act(async () => { finish(kline()); });
  expect(result.current.active).toBe(nextProps.daily);
  expect(result.current.visible).toBeNull();
  expect(fetchStockNineTurnSeries).not.toHaveBeenCalled();
});
