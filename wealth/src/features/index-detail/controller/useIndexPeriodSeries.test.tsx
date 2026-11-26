import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DetailChartHistoryViewport } from "../../../shared/charts/detail-workspace/detailChartTypes";
import type { fetchIndexDetailKline } from "../api/indexDetailApiClient";
import type { IndexDetailKlineResponseDto, IndexLongPeriod } from "../api/indexDetailApiTypes";
import { makeKline } from "../testing/indexDetailTestFixtures";
import { useIndexPeriodSeries } from "./useIndexPeriodSeries";

const TS_CODE = "000001.SH";
const FIRST_END = "2026-11-20";
const NEXT_END = "2017-02-10";

function page(endDate: string, { count = 1, next = null, period = "week", code = TS_CODE }: {
  count?: number; next?: string | null; period?: IndexLongPeriod; code?: string;
} = {}): IndexDetailKlineResponseDto {
  const daily = makeKline(code);
  const bars = Array.from({ length: count }, (_, index) => ({
    ...daily.bars[0]!,
    // Weekly/monthly producers return only the four common factor groups.
    factors: { ma: daily.bars[0]!.factors.ma, boll: daily.bars[0]!.factors.boll,
      macd: daily.bars[0]!.factors.macd, kdj: daily.bars[0]!.factors.kdj },
    // Dates here isolate ordering and paging. The real holiday dates are checked against the backend.
    tradeDate: new Date(Date.parse(endDate) - (count - index - 1) * 7 * 86_400_000).toISOString().slice(0, 10),
  }));
  return {
    ...daily, period, bars,
    meta: { count, limit: 500, startDate: null, endDate, nextEndDate: next },
    dataStatus: {
      status: count ? "READY" : "EMPTY", expectedTradeDate: endDate, observedTradeDate: count ? endDate : null,
    },
  };
}

function deferred() {
  let resolve!: (value: IndexDetailKlineResponseDto) => void;
  const promise = new Promise<IndexDetailKlineResponseDto>((complete) => { resolve = complete; });
  return { promise, resolve };
}

function viewport(first: string, overrides: Partial<DetailChartHistoryViewport> = {}): DetailChartHistoryViewport {
  return { firstDate: first, leftDate: first, remaining: 1, direction: "history", beyondLeft: true,
    gesture: Symbol(), ...overrides };
}

describe("index weekly and monthly chart requests", () => {
  it("starts one history request at the threshold, caches newer-view arrivals and stops at the end", async () => {
    const first = page(FIRST_END, { count: 500, next: NEXT_END });
    const older = deferred();
    const request = vi.fn<typeof fetchIndexDetailKline>().mockResolvedValueOnce(first).mockReturnValueOnce(older.promise);
    const { result } = renderHook(() => useIndexPeriodSeries(TS_CODE, "week", FIRST_END, request));
    await waitFor(() => expect(result.current.candles).toHaveLength(500));
    expect(request.mock.calls[0]?.[0]).toEqual({ tsCode: TS_CODE, period: "week", endDate: FIRST_END, limit: 500 });
    const oldest = result.current.candles[0]!.time;
    const near = viewport(oldest, { remaining: 100, leftDate: result.current.candles[99]!.time });
    act(() => {
      result.current.onViewport({ ...near, direction: "stationary" });
      result.current.onViewport({ ...near, remaining: 101 });
    });
    expect(request).toHaveBeenCalledTimes(1);

    act(() => {
      result.current.onViewport(near);
      result.current.onViewport(near);
      result.current.onViewport({ ...near, direction: "recent", leftDate: FIRST_END, remaining: 500 });
    });
    expect(request).toHaveBeenCalledTimes(2);
    expect(request.mock.calls[1]?.[0]).toEqual({ tsCode: TS_CODE, period: "week", endDate: NEXT_END, limit: 500 });
    await act(async () => older.resolve(page(NEXT_END, { count: 500 })));
    expect(result.current.candles).toHaveLength(500);

    act(() => result.current.onViewport(near));
    expect(result.current.candles).toHaveLength(1000);
    expect(result.current.candles[499]?.time).toBe(NEXT_END);
    expect(result.current.candles[500]?.time).toBe(oldest);
    act(() => result.current.onViewport(viewport(result.current.candles[0]!.time)));
    expect(request).toHaveBeenCalledTimes(2);
  });

  it("cancels an old period and index, ignores late results, and refreshes the latest month for a new cutoff", async () => {
    const weekly = deferred(), oldIndexMonth = deferred();
    const request = vi.fn<typeof fetchIndexDetailKline>()
      .mockReturnValueOnce(weekly.promise).mockReturnValueOnce(oldIndexMonth.promise)
      .mockResolvedValueOnce(page(FIRST_END, { period: "month", code: "399001.SZ" }))
      .mockResolvedValueOnce(page("2026-11-23", { period: "month", code: "399001.SZ" }));
    const { result, rerender, unmount } = renderHook(
      ({ code, period, end }) => useIndexPeriodSeries(code, period, end, request),
      { initialProps: { code: TS_CODE, period: "week" as IndexLongPeriod, end: FIRST_END } },
    );
    rerender({ code: TS_CODE, period: "month", end: FIRST_END });
    expect(request.mock.calls[0]?.[1]?.signal?.aborted).toBe(true);
    rerender({ code: "399001.SZ", period: "month", end: FIRST_END });
    expect(request.mock.calls[1]?.[1]?.signal?.aborted).toBe(true);
    await waitFor(() => expect(result.current.candles.map(candle => candle.fullDate)).toEqual([FIRST_END]));
    await act(async () => {
      weekly.resolve(page(FIRST_END, { count: 2 }));
      oldIndexMonth.resolve(page(FIRST_END, { count: 2, period: "month" }));
    });
    expect(result.current.candles).toHaveLength(1);

    rerender({ code: "399001.SZ", period: "month", end: "2026-11-23" });
    await waitFor(() => expect(result.current.candles.map(candle => candle.fullDate)).toEqual(["2026-11-23"]));
    unmount();
    expect(request.mock.calls[3]?.[1]?.signal?.aborted).toBe(true);
  });

  it("retries a failed first page and retries the same history cursor once per new gesture", async () => {
    const first = page(FIRST_END, { count: 500, next: NEXT_END });
    const request = vi.fn<typeof fetchIndexDetailKline>().mockRejectedValueOnce(new Error("unavailable"))
      .mockResolvedValueOnce(first).mockResolvedValueOnce(page(NEXT_END, { code: "399001.SZ" }))
      .mockResolvedValueOnce(page(NEXT_END, { count: 0 }));
    const { result } = renderHook(() => useIndexPeriodSeries(TS_CODE, "week", FIRST_END, request));
    await waitFor(() => expect(result.current.phase).toBe("error"));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.candles).toHaveLength(500));

    const firstGesture = viewport(result.current.candles[0]!.time);
    act(() => result.current.onViewport(firstGesture));
    await waitFor(() => expect(result.current.historyPhase).toBe("error"));
    expect(result.current.candles).toHaveLength(500);
    act(() => {
      result.current.onViewport(firstGesture);
      result.current.onViewport({ ...firstGesture, gesture: Symbol(), beyondLeft: false });
    });
    expect(request).toHaveBeenCalledTimes(3);

    act(() => result.current.onViewport({ ...firstGesture, gesture: Symbol() }));
    await waitFor(() => expect(result.current.historyPhase).toBe("idle"));
    expect(request.mock.calls[3]?.[0].endDate).toBe(NEXT_END);
    act(() => result.current.onViewport(viewport(result.current.candles[0]!.time)));
    expect(request).toHaveBeenCalledTimes(4);
    expect(result.current.candles).toHaveLength(500);
  });

  it("rejects an out-of-order page and preserves chart data for delayed or partial responses", async () => {
    const unordered = page(FIRST_END, { count: 2 });
    unordered.bars.reverse();
    const delayed = page(FIRST_END);
    delayed.dataStatus.status = "DELAYED";
    const partial = page(FIRST_END, { period: "month" });
    partial.dataStatus.status = "PARTIAL";
    const request = vi.fn<typeof fetchIndexDetailKline>()
      .mockResolvedValueOnce(unordered).mockResolvedValueOnce(delayed).mockResolvedValueOnce(partial);
    const { result, rerender } = renderHook(
      ({ period }) => useIndexPeriodSeries(TS_CODE, period, FIRST_END, request),
      { initialProps: { period: "week" as IndexLongPeriod } },
    );
    await waitFor(() => expect(result.current.phase).toBe("error"));
    act(() => result.current.retry());
    await waitFor(() => expect(result.current.phase).toBe("delayed"));
    expect(result.current.candles).toHaveLength(1);
    rerender({ period: "month" });
    await waitFor(() => expect(result.current.phase).toBe("partial"));
    expect(result.current.candles).toHaveLength(1);
  });
});
