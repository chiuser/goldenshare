import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type { DetailChartHistoryViewport } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { fetchStockNineTurnSeries } from "../../nine-turn/api/nineTurnApiClient";
import type { NineTurnMarkerDto } from "../../nine-turn/api/nineTurnApiTypes";
import { fetchStockDetailKline } from "../api/stockDetailApiClient";
import type { StockDetailDailyKlineResponseDto, StockDetailKlineResponseDto, StockDailyKlineBarDto } from "../api/stockDetailApiTypes";
import { toCandlePoint } from "../api/stockDetailViewModelAdapter";
import { fetchStockTrendChannel } from "../trend-channel/api/stockTrendChannelApiClient";
import { useStockDailyHistory } from "./useStockDailyHistory";

vi.mock("../api/stockDetailApiClient");
vi.mock("../../nine-turn/api/nineTurnApiClient");
vi.mock("../trend-channel/api/stockTrendChannelApiClient");

const code = "600519.SH";
const anchor = "2026-11-19";
const end = "2024-10-29";
const start = "2024-10-28";
const first = "2024-10-30";
const marker: NineTurnMarkerDto =
  { tradeDate: start, tradeTime: null, direction: "UP", sequenceNumber: 1, completed: false };

function bar(tradeDate: string): StockDailyKlineBarDto {
  return {
    tradeDate, open: 10, high: 11, low: 9, close: 10.5, volDisplay: "100",
    factors: { ma: { ma5: 10 }, boll: {}, macd: {}, kdj: {},
      trendChannel: { shortUpper: 11, shortLower: 9, longUpper: 12, longLower: 8 } },
  };
}

const seed = {
  tsCode: code, tradeDate: anchor, nextEndDate: end,
  candles: [bar(first), bar(anchor)].map(toCandlePoint),
};

function kline(): StockDetailDailyKlineResponseDto {
  return {
    pageContext: {
      tradeDate: end, market: "CN_A", isTradingDay: true, sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai", generatedAt: "2026-11-20T10:00:00+08:00", source: "explicit",
    },
    stockRef: { tsCode: code }, period: "day", adjustment: "forward", sourceAdjustment: "qfq",
    bars: [bar(start), bar(end)], meta: { count: 2, limit: 500, endDate: end, nextEndDate: null },
    dataStatus: { status: "READY", expectedTradeDate: end, observedTradeDate: end },
    nineTurnMarkers: [marker],
  };
}

function viewport(overrides: Partial<DetailChartHistoryViewport> = {}): DetailChartHistoryViewport {
  return { firstDate: first, leftDate: first, remaining: 1, direction: "history", beyondLeft: true,
    gesture: Symbol(), ...overrides };
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchStockDetailKline).mockResolvedValue(kline());
});

it("prepends candles and nine-turn together, and retries trend separately", async () => {
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
  await waitFor(() => expect(result.current.visible?.pages[0]?.nineTurnMarkers).toEqual([marker]));
  expect(fetchStockDetailKline).toHaveBeenCalledExactlyOnceWith(
    expect.objectContaining({ tsCode: code, tradeDate: anchor, endDate: end, limit: 500 }), expect.anything(),
  );
  expect(fetchStockNineTurnSeries).not.toHaveBeenCalled();
  expect(result.current.visible?.candles.map(candle => candle.fullDate)).toEqual([start, end, first, anchor]);
  expect(fetchStockTrendChannel).not.toHaveBeenCalled();
  expect(result.current.visible?.pages[0]?.trendPoints).toEqual([
    { time: start, close: 10.5, shortUpper: 11, shortLower: 9, longUpper: 12, longLower: 8 },
    { time: end, close: 10.5, shortUpper: 11, shortLower: 9, longUpper: 12, longLower: 8 },
  ]);
  expect(fetchStockTrendChannel).not.toHaveBeenCalled();
  act(() => result.current.onViewport(viewport({ firstDate: start })));
  expect(fetchStockDetailKline).toHaveBeenCalledTimes(1);
  expect(fetchStockNineTurnSeries).not.toHaveBeenCalled();
});

it.each(["failed request", "missing nine-turn field", "missing rail", "nonfinite rail", "wrong date"])("retries the same end date after a %s", async (failure) => {
  if (failure === "failed request") {
    vi.mocked(fetchStockDetailKline).mockRejectedValueOnce(new Error("kline failed"));
  } else if (failure === "missing nine-turn field") {
    vi.mocked(fetchStockDetailKline).mockResolvedValueOnce({ ...kline(), nineTurnMarkers: undefined });
  } else {
    const invalid = kline();
    // Deliberately invalid server input verifies that conversion fails before the cursor changes.
    if (failure === "missing rail") Object.assign(invalid.bars[0]!.factors.trendChannel, { shortUpper: undefined });
    if (failure === "nonfinite rail") invalid.bars[0]!.factors.trendChannel.longUpper = NaN;
    if (failure === "wrong date") invalid.bars[0]!.tradeDate = "bad-date";
    vi.mocked(fetchStockDetailKline).mockResolvedValueOnce(invalid);
  }
  const { result } = renderHook(() => useStockDailyHistory(seed, true));
  const gesture = viewport();
  act(() => result.current.onViewport(gesture));
  await waitFor(() => expect(result.current.visible?.phase).toBe("error"));
  expect(result.current.visible?.candles).toEqual(seed.candles);
  expect(result.current.visible?.pages).toEqual([]);
  act(() => result.current.onViewport(gesture));
  expect(fetchStockDetailKline).toHaveBeenCalledTimes(1);
  act(() => result.current.onViewport(viewport()));
  await waitFor(() => expect(result.current.visible?.candles.length).toBe(4));
  expect(fetchStockDetailKline).toHaveBeenLastCalledWith(expect.objectContaining({ endDate: end }), expect.anything());
  expect(result.current.visible?.pages[0]?.nineTurnMarkers).toEqual([marker]);
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
