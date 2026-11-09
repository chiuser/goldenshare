import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchIndexDetailKline, fetchIndexDetailPageInit, IndexDetailApiError } from "../api/indexDetailApiClient";
import type { IndexDetailKlineResponseDto, IndexDetailPageInitResponseDto } from "../api/indexDetailApiTypes";
import { fetchTrendChannel } from "../api/trendChannelApiClient";
import { makeKline, makeOrdinaryKline, makePageInit, makeTrendPayload } from "../testing/indexDetailTestFixtures";
import { loadIndexNineTurnSeries } from "../api/indexNineTurnLoader";
import type { NineTurnSeriesDto } from "../../nine-turn/api/nineTurnApiTypes";
import { useIndexDetailController } from "./useIndexDetailController";

vi.mock("../api/indexDetailApiClient", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/indexDetailApiClient")>(),
  fetchIndexDetailPageInit: vi.fn(),
  fetchIndexDetailKline: vi.fn(),
}));
vi.mock("../api/trendChannelApiClient", () => ({ fetchTrendChannel: vi.fn() }));
vi.mock("../api/indexNineTurnLoader", () => ({ loadIndexNineTurnSeries: vi.fn() }));

const requestedCode = "399001.SZ";
beforeEach(() => vi.resetAllMocks());

// Producer: index_detail_page_query_service.py:73-109, index_detail.py:168-180.
// A legal EMPTY response retains its index and has no quote/asOf/basic/breadth.
function emptyPageInit(tsCode: string): IndexDetailPageInitResponseDto {
  return {
    ...makePageInit(tsCode),
    asOfTradeDate: null,
    quote: null,
    dailyBasic: null,
    constituentBreadth: null,
    dataStatus: { status: "EMPTY", expectedTradeDate: "2026-07-31", observedTradeDate: null },
  };
}

// Producer: index_detail_kline_query_service.py:99-133/177-197, index_detail.py:246-265.
// Match this controller's limit=500 and no startDate; EMPTY has zero bars/count.
function dailyKline(tsCode: string, empty: boolean): IndexDetailKlineResponseDto {
  const response = makeKline(tsCode);
  return {
    ...response,
    bars: empty ? [] : response.bars,
    meta: { count: empty ? 0 : 2, limit: 500, startDate: null, endDate: "2026-07-31" },
    dataStatus: empty
      ? { status: "EMPTY", expectedTradeDate: "2026-07-31", observedTradeDate: null }
      : response.dataStatus,
  };
}

describe("current index identity is checked before empty data", () => {
  it.each([
    { label: "same-code EMPTY", responseCode: "399001.SZ", empty: true, phase: "empty", errorCode: "" },
    { label: "wrong-code EMPTY", responseCode: "000001.SH", empty: true, phase: "error", errorCode: "ID_QUERY_FAILED" },
    { label: "wrong-code nonempty", responseCode: "000001.SH", empty: false, phase: "error", errorCode: "ID_QUERY_FAILED" },
  ])("page-init $label does not start downstream requests", async ({ responseCode, empty, phase, errorCode }) => {
    // Wrong-code cases substitute another valid index response, not missing fields.
    vi.mocked(fetchIndexDetailPageInit).mockResolvedValue(empty ? emptyPageInit(responseCode) : makePageInit(responseCode));

    const { result } = renderHook(() => useIndexDetailController(requestedCode, undefined));
    await waitFor(() => expect(result.current.phase).toBe(phase));

    expect(result.current.errorCode).toBe(errorCode);
    expect(fetchIndexDetailPageInit).toHaveBeenCalledTimes(1);
    expect(fetchIndexDetailPageInit).toHaveBeenCalledWith(
      { tsCode: "399001.SZ", tradeDate: undefined },
      { signal: expect.any(AbortSignal) },
    );
    expect(fetchIndexDetailKline).not.toHaveBeenCalled();
    expect(fetchTrendChannel).not.toHaveBeenCalled();
    if (phase === "empty") {
      expect(result.current.viewModel?.identity.tsCode).toBe("399001.SZ");
      expect(result.current.viewModel?.chart.candles).toEqual([]);
    } else {
      expect(result.current.viewModel).toBeNull();
    }
  });

  it.each([
    { label: "same-code EMPTY", responseCode: "399001.SZ", empty: true, phase: "empty", errorCode: "" },
    { label: "wrong-code EMPTY", responseCode: "000001.SH", empty: true, phase: "error", errorCode: "ID_QUERY_FAILED" },
    { label: "wrong-code nonempty", responseCode: "000001.SH", empty: false, phase: "error", errorCode: "ID_QUERY_FAILED" },
  ])("kline $label after valid page-init keeps the correct terminal state", async ({ responseCode, empty, phase, errorCode }) => {
    vi.mocked(fetchIndexDetailPageInit).mockResolvedValue(makePageInit(requestedCode));
    vi.mocked(fetchIndexDetailKline).mockResolvedValue(dailyKline(responseCode, empty));

    const { result } = renderHook(() => useIndexDetailController(requestedCode, undefined));
    await waitFor(() => expect(result.current.phase).toBe(phase));

    expect(result.current.errorCode).toBe(errorCode);
    expect(fetchIndexDetailPageInit).toHaveBeenCalledTimes(1);
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(1);
    expect(fetchIndexDetailKline).toHaveBeenCalledWith(
      { tsCode: "399001.SZ", period: "day", endDate: "2026-07-31", limit: 500 },
      { signal: expect.any(AbortSignal) },
    );
    expect(fetchTrendChannel).not.toHaveBeenCalled();
    if (phase === "empty") {
      expect(result.current.viewModel?.identity.tsCode).toBe("399001.SZ");
      expect(result.current.viewModel?.chart.candles).toEqual([]);
    } else {
      expect(result.current.viewModel).toBeNull();
    }
  });
});

describe("SSE ordinary daily history", () => {
  const code = "000001.SH";
  const firstEnd = "2026-07-31";

  // Input shape follows the implemented SSE page contract. Weekday dates are
  // sufficient to verify the cursor supplied by the server and the drag threshold.
  function page(endDate: string, count: number, nextEndDate: string | null): IndexDetailKlineResponseDto {
    const initial = makeOrdinaryKline();
    const rows = [];
    const date = new Date(endDate);
    while (rows.length < count) {
      if (date.getUTCDay() !== 0 && date.getUTCDay() !== 6) {
        rows.push({ ...initial.bars[0]!, tradeDate: date.toISOString().slice(0, 10) });
      }
      date.setUTCDate(date.getUTCDate() - 1);
    }
    return {
      ...initial, bars: rows.reverse(),
      meta: { count, limit: 500, startDate: null, endDate, nextEndDate },
      dataStatus: count === 0
        ? { status: "EMPTY", expectedTradeDate: endDate, observedTradeDate: null }
        : { status: "READY", expectedTradeDate: endDate, observedTradeDate: endDate },
    };
  }

  function mountFirstPage() {
    const sample = page(firstEnd, 500, null);
    const firstDate = sample.bars[0]!.tradeDate;
    const friday = new Date(firstDate);
    friday.setUTCDate(friday.getUTCDate() - 3);
    expect(new Date(firstDate).getUTCDay()).toBe(1);
    const olderEnd = friday.toISOString().slice(0, 10);
    const initial = page(firstEnd, 500, olderEnd);
    vi.mocked(fetchIndexDetailPageInit).mockResolvedValue(makePageInit(code));
    vi.mocked(fetchIndexDetailKline).mockResolvedValueOnce(initial);
    vi.mocked(fetchTrendChannel).mockResolvedValueOnce(makeTrendPayload());
    const hook = renderHook(({ tsCode }) => useIndexDetailController(tsCode, undefined), { initialProps: { tsCode: code } });
    const move = (remaining: number, direction: "history" | "recent", gesture = Symbol(), beyondLeft = false) =>
      act(() => hook.result.current.history.onViewport({
        firstDate, leftDate: initial.bars[remaining - 1]!.tradeDate,
        remaining, direction, gesture, beyondLeft,
      }));
    return { ...hook, move, olderEnd };
  }

  it("keeps a late short page in cache, then reveals it with both layers and retries only the failed range", async () => {
    const { result, move, olderEnd } = mountFirstPage();
    const older = page(olderEnd, 2, null);
    const startDate = older.bars[0]!.tradeDate;
    let complete!: (value: IndexDetailKlineResponseDto) => void;
    vi.mocked(fetchIndexDetailKline).mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    const trend = makeTrendPayload();
    // A trend page is allowed to have points for only some of the K-line dates.
    const trendPart = {
      ...trend, bars: [{ ...trend.bars[0]!, trade_date: olderEnd }],
      meta: { ...trend.meta, bar_count: 1, limit: 500, start_date: olderEnd, end_date: olderEnd },
    };
    vi.mocked(fetchTrendChannel).mockResolvedValueOnce(trendPart);
    vi.mocked(loadIndexNineTurnSeries).mockRejectedValueOnce(new Error("九转读取失败"));
    const marker = { tradeDate: olderEnd, tradeTime: null, sequenceNumber: 7, direction: "UP", completed: false } as const;
    const nineTurn: NineTurnSeriesDto = {
      tsCode: code, subjectType: "index", period: "day", debugInfo: null,
      dataStatus: { status: "READY", code: null, message: null, expectedEndDate: olderEnd, observedEndDate: olderEnd },
      latestMarker: marker, markers: [marker],
      meta: { startDate, endDate: olderEnd, comparisonLag: 4, formulaVersion: 1, signalThreshold: 9,
        markerCount: 1, sourceRowCount: 2, matchedRowCount: 2, missingRowCount: 0, observedStartDate: startDate,
        observedEndDate: olderEnd, limit: 500, hasMore: false, nextCursor: null },
    };
    vi.mocked(loadIndexNineTurnSeries).mockResolvedValueOnce(nineTurn);
    await waitFor(() => expect(result.current.history.active).toBe(true));
    move(101, "history");
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(1);
    move(100, "history");
    move(99, "history");
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(2);
    expect(fetchIndexDetailKline).toHaveBeenLastCalledWith(
      { tsCode: code, period: "day", limit: 500, endDate: olderEnd }, { signal: expect.any(AbortSignal) },
    );
    move(140, "recent");
    await act(async () => complete(older));
    expect(result.current.history.visible).toBeNull();
    expect(loadIndexNineTurnSeries).toHaveBeenCalledTimes(1);
    expect(loadIndexNineTurnSeries).toHaveBeenLastCalledWith(
      { tsCode: code, subjectType: "index", period: "day", startDate, endDate: olderEnd, limit: 500 },
      { signal: expect.any(AbortSignal) },
    );
    expect(fetchTrendChannel).toHaveBeenCalledTimes(2);
    expect(fetchTrendChannel).toHaveBeenLastCalledWith(
      { startDate, endDate: olderEnd, limit: 500 }, { signal: expect.any(AbortSignal) },
    );
    move(100, "history");
    const visible = result.current.history.visible;
    expect(visible?.candles).toHaveLength(502);
    expect(visible?.candles.slice(0, 2).map(bar => bar.time)).toEqual([startDate, olderEnd]);
    expect(visible?.trendPoints.map(point => point.time)).toEqual([olderEnd]);
    const failure = visible?.failedLayers[0]!;
    expect(failure.layer).toBe("nineTurn");
    await act(async () => result.current.history.retryLayer(failure.page, failure.layer));
    expect(loadIndexNineTurnSeries).toHaveBeenCalledTimes(2);
    expect(loadIndexNineTurnSeries).toHaveBeenLastCalledWith(
      { tsCode: code, subjectType: "index", period: "day", startDate, endDate: olderEnd, limit: 500 },
      { signal: expect.any(AbortSignal) },
    );
    expect(fetchTrendChannel).toHaveBeenCalledTimes(2);
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(2);
    expect(result.current.history.visible?.nineTurnMarkers).toEqual([marker]);
    expect(result.current.history.visible?.failedLayers).toEqual([]);
    act(() => result.current.history.onViewport({
      firstDate: startDate, leftDate: startDate, remaining: 1, direction: "history", beyondLeft: true, gesture: Symbol(),
    }));
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(2);
  });

  it("retries the same date only on a new left-edge gesture and stops on a successful empty page", async () => {
    const { result, move, olderEnd } = mountFirstPage();
    vi.mocked(fetchIndexDetailKline).mockRejectedValueOnce(new IndexDetailApiError(
      "000001.SH 2024-01-01 收盘价缺失", 500, "ID_QUERY_FAILED",
    )).mockResolvedValueOnce(page(olderEnd, 0, null));
    await waitFor(() => expect(result.current.history.active).toBe(true));
    const firstGesture = Symbol();
    move(1, "history", firstGesture, true);
    await waitFor(() => expect(result.current.history.phase).toBe("error"));
    expect(result.current.history.error).toContain("收盘价缺失");
    move(1, "history", firstGesture, true);
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(2);
    move(1, "history", Symbol(), true);
    await waitFor(() => expect(result.current.history.phase).toBe("idle"));
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(3);
    expect(vi.mocked(fetchIndexDetailKline).mock.calls.slice(1).map(([request]) => request.endDate)).toEqual([olderEnd, olderEnd]);
    expect(result.current.history.visible).toBeNull();
    expect(result.current.viewModel?.chart.candles).toHaveLength(500);
    expect(loadIndexNineTurnSeries).not.toHaveBeenCalled();
    move(1, "history", Symbol(), true);
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(3);
  });

  it("cancels old history and ignores its response after switching the index", async () => {
    const { result, rerender, move, olderEnd } = mountFirstPage();
    let complete!: (value: IndexDetailKlineResponseDto) => void;
    vi.mocked(fetchIndexDetailKline).mockImplementationOnce(() => new Promise(resolve => { complete = resolve; }));
    vi.mocked(fetchIndexDetailKline).mockResolvedValueOnce(makeOrdinaryKline("399001.SZ"));
    await waitFor(() => expect(result.current.history.active).toBe(true));
    move(100, "history");
    const signal = vi.mocked(fetchIndexDetailKline).mock.calls[1]?.[1]?.signal;
    vi.mocked(fetchIndexDetailPageInit).mockResolvedValue(makePageInit("399001.SZ"));
    rerender({ tsCode: "399001.SZ" });
    await waitFor(() => expect(result.current.viewModel?.identity.tsCode).toBe("399001.SZ"));
    expect(signal?.aborted).toBe(true);
    await act(async () => complete(page(olderEnd, 2, null)));
    expect(result.current.history.visible).toBeNull();
    expect(loadIndexNineTurnSeries).not.toHaveBeenCalled();
  });
});
