import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useIndexDetailController } from "../controller/useIndexDetailController";
import { makeKline, makeOrdinaryKline, makePageInit } from "../testing/indexDetailTestFixtures";
import { fetchIndexDetailKline } from "./indexDetailApiClient";
import { buildIndexDetailViewModel, toCandlePoint } from "./indexDetailViewModelAdapter";

// Inputs follow the current Kline/PageInit DTO through the existing fixture
// builders. Expected request parameters below
// are literal values from LLD 15.4.1, not derived from the page constant.
afterEach(() => vi.unstubAllGlobals());

describe("index daily history requests", () => {
  it("passes the research start/end, 1000 limit and cancellation signal unchanged", async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json(makeKline()));
    vi.stubGlobal("fetch", fetch);
    const controller = new AbortController();

    await fetchIndexDetailKline({ tsCode: "000001.SH", period: "day",
      startDate: "2023-10-24", endDate: "2026-10-21", limit: 1000 },
    { signal: controller.signal });

    const [input, options] = fetch.mock.calls[0]!;
    const url = new URL(String(input));
    expect(url.pathname).toBe("/api/v1/wealth/market/index-detail/kline");
    expect(Object.fromEntries(url.searchParams)).toEqual({ tsCode: "000001.SH", period: "day",
      startDate: "2023-10-24", endDate: "2026-10-21", limit: "1000" });
    expect(options.signal).toBe(controller.signal);
  });

  it("gets four rails from the same 500 Klines on initial load and whole-page retry", async () => {
    const fetch = vi.fn().mockImplementation(async (input: RequestInfo | URL) => {
      const path = new URL(String(input)).pathname;
      if (path.endsWith("/page-init")) return Response.json(makePageInit());
      if (path.endsWith("/kline")) return Response.json(makeOrdinaryKline());
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetch);
    const { result } = renderHook(() => useIndexDetailController("000001.SH", undefined));
    await waitFor(() => expect(result.current.phase).toBe("ready"));
    expect(result.current.dailyTrendPoints).toHaveLength(2);
    act(() => result.current.retry());
    await waitFor(() => expect(requests("/kline")).toHaveLength(2));
    await waitFor(() => expect(result.current.phase).toBe("ready"));

    expect(requests("/kline").map(url => [url.searchParams.get("limit"), url.searchParams.get("endDate")]))
      .toEqual([["500", "2026-07-31"], ["500", "2026-07-31"]]);
    expect(requests("/trend-channel")).toHaveLength(0);
    expect(result.current.viewModel?.chart.candles).toHaveLength(2);

    function requests(suffix: string) {
      return fetch.mock.calls.map(([input]) => new URL(String(input))).filter(url => url.pathname.endsWith(suffix));
    }
  });

  it("keeps all returned bars and maps the original MACD values without rounding or reseeding", () => {
    const kline = makeKline();
    const base = kline.bars[0]!;
    const bars = Array.from({ length: 1000 }, (_, offset) => ({
      ...base,
      tradeDate: new Date(Date.UTC(2023, 0, 1 + offset)).toISOString().slice(0, 10),
      close: 100 + offset,
      factors: { ...base.factors, macd: { dif: -0.873123, dea: -1.110111, macd: 0.473976 } },
    }));
    const full = buildIndexDetailViewModel(makePageInit(), { ...kline, bars,
      meta: { ...kline.meta, count: 1000, limit: 1000 } });
    const previous = buildIndexDetailViewModel(makePageInit(), { ...kline, bars: bars.slice(-300),
      meta: { ...kline.meta, count: 300, limit: 300 } });

    expect(full.chart.candles).toHaveLength(1000);
    expect(full.chart.candles[0]?.close).toBe(100);
    expect(full.chart.candles.at(-1)?.close).toBe(1099);
    expect(full.chart.candles.slice(-300)).toEqual(previous.chart.candles);
    expect(toCandlePoint(bars[0]!)).toMatchObject({ close: 100, dif: -0.873123,
      dea: -1.110111, macd: 0.473976 });
  });
});
