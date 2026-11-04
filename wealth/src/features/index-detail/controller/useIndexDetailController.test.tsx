import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchIndexDetailKline, fetchIndexDetailPageInit } from "../api/indexDetailApiClient";
import type { IndexDetailKlineResponseDto, IndexDetailPageInitResponseDto } from "../api/indexDetailApiTypes";
import { fetchTrendChannel } from "../api/trendChannelApiClient";
import { makeKline, makePageInit } from "../testing/indexDetailTestFixtures";
import { useIndexDetailController } from "./useIndexDetailController";

vi.mock("../api/indexDetailApiClient", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/indexDetailApiClient")>(),
  fetchIndexDetailPageInit: vi.fn(),
  fetchIndexDetailKline: vi.fn(),
}));
vi.mock("../api/trendChannelApiClient", () => ({ fetchTrendChannel: vi.fn() }));

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
// Match this controller's limit=1000 and no startDate; EMPTY has zero bars/count.
function dailyKline(tsCode: string, empty: boolean): IndexDetailKlineResponseDto {
  const response = makeKline(tsCode);
  return {
    ...response,
    bars: empty ? [] : response.bars,
    meta: { count: empty ? 0 : 2, limit: 1000, startDate: null, endDate: "2026-07-31" },
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

    const { result } = renderHook(() => useIndexDetailController(requestedCode, ""));
    await waitFor(() => expect(result.current.phase).toBe(phase));

    expect(result.current.errorCode).toBe(errorCode);
    expect(fetchIndexDetailPageInit).toHaveBeenCalledTimes(1);
    expect(fetchIndexDetailPageInit).toHaveBeenCalledWith(
      { tsCode: "399001.SZ", tradeDate: undefined, debug: undefined },
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

    const { result } = renderHook(() => useIndexDetailController(requestedCode, ""));
    await waitFor(() => expect(result.current.phase).toBe(phase));

    expect(result.current.errorCode).toBe(errorCode);
    expect(fetchIndexDetailPageInit).toHaveBeenCalledTimes(1);
    expect(fetchIndexDetailKline).toHaveBeenCalledTimes(1);
    expect(fetchIndexDetailKline).toHaveBeenCalledWith(
      { tsCode: "399001.SZ", period: "day", endDate: "2026-07-31", limit: 1000, debug: undefined },
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
