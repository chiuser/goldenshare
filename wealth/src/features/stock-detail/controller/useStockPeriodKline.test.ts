import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { fetchStockDetailKline } from "../api/stockDetailApiClient";
import type { StockDetailKlineResponseDto } from "../api/stockDetailApiTypes";
import { useStockPeriodKline } from "./useStockPeriodKline";

vi.mock("../api/stockDetailApiClient", () => ({ fetchStockDetailKline: vi.fn() }));
const fetchKline = vi.mocked(fetchStockDetailKline);
const anchor = "2026-11-23";

function page(period: "week" | "month", tradeDate: string, nextEndDate: string | null,
              status: "READY" | "DELAYED" = "READY"): StockDetailKlineResponseDto {
  return {
    period, adjustment: "forward", sourceAdjustment: "qfq", stockRef: { tsCode: "000001.SZ" },
    pageContext: { market: "CN_A", tradeDate: anchor, isTradingDay: true,
                   sessionStatus: "CLOSED", timezone: "Asia/Shanghai", generatedAt: `${anchor}T21:00:00+08:00`,
                   source: "explicit" },
    meta: { count: 1, limit: 100, nextEndDate },
    dataStatus: { status, expectedTradeDate: anchor, observedTradeDate: tradeDate },
    bars: [{ tradeDate, close: 12.34, volDisplay: null,
             factors: { ma: { ma5: 12.1 }, boll: {}, macd: {}, kdj: {} } }],
    nineTurnMarkers: [{ tradeDate, tradeTime: null, sequenceNumber: 9, completed: true, direction: "UP" }],
  };
}

afterEach(() => fetchKline.mockReset());

it("retries a failed older page with the same cursor and keeps the first-page status", async () => {
  fetchKline.mockResolvedValueOnce(page("week", "2026-11-20", "2026-11-13", "DELAYED"))
    .mockRejectedValueOnce(new Error("读取失败"))
    .mockResolvedValueOnce(page("week", "2026-11-13", null));
  const { result } = renderHook(() => useStockPeriodKline("000001.SZ", "week", anchor));
  await waitFor(() => expect(result.current.data?.candles).toHaveLength(1));
  act(() => result.current.onViewport({ direction: "history", beyondLeft: true,
                                       firstDate: "2026-11-20", leftDate: "2026-11-20", remaining: 0 }));
  await waitFor(() => expect(result.current.data?.phase).toBe("error"));
  expect(result.current.data?.candles[0]?.time).toBe("2026-11-20");
  act(() => result.current.retry());
  await waitFor(() => expect(result.current.data?.candles.map(bar => bar.time)).toEqual(["2026-11-13", "2026-11-20"]));
  expect(result.current.data?.markers.map(marker => marker.tradeDate)).toEqual(["2026-11-13", "2026-11-20"]);
  expect(result.current.data?.dataStatus?.status).toBe("DELAYED");
  expect(fetchKline.mock.calls.slice(1).map(([request]) => [request.tradeDate, request.endDate])).toEqual([
    [anchor, "2026-11-13"], [anchor, "2026-11-13"],
  ]);
});

it("cancels the previous period and loads a fresh first page when switching back", async () => {
  let resolveOld!: (response: StockDetailKlineResponseDto) => void;
  fetchKline.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
    .mockResolvedValueOnce(page("month", anchor, null))
    .mockResolvedValueOnce(page("week", "2026-11-20", null, "DELAYED"))
    .mockResolvedValueOnce(page("month", anchor, null))
    .mockResolvedValueOnce(page("week", anchor, null));
  const { result, rerender } = renderHook(({ period }: { period: "week" | "month" }) =>
    useStockPeriodKline("000001.SZ", period, anchor), { initialProps: { period: "week" } });
  rerender({ period: "month" });
  await waitFor(() => expect(result.current.data?.candles[0]?.time).toBe(anchor));
  expect(fetchKline.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
  await act(async () => resolveOld(page("week", "2026-11-20", null)));
  expect(result.current.data?.period).toBe("month");
  expect(result.current.data?.candles[0]?.time).toBe(anchor);
  expect(fetchKline.mock.calls[1]?.[0].limit).toBeUndefined();
  rerender({ period: "week" });
  await waitFor(() => expect(result.current.data?.dataStatus?.status).toBe("DELAYED"));
  rerender({ period: "month" });
  await waitFor(() => expect(result.current.data?.dataStatus?.status).toBe("READY"));
  rerender({ period: "week" });
  await waitFor(() => expect(result.current.data?.dataStatus?.status).toBe("READY"));
  expect(result.current.data?.candles[0]?.time).toBe(anchor);
});
