import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  IndexDetailMinuteFrequency,
  IndexMinuteIndicatorsResponseDto,
  IndexMinutesResponseDto,
} from "../api/indexDetailApiTypes";
import { useIndexMinuteSeries } from "./useIndexMinuteSeries";

const PARAMS_KEY = "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3";

describe("useIndexMinuteSeries", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("caches each frequency independently and requests real bars plus indicators once", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      const freq = Number(url.searchParams.get("freq")) as IndexDetailMinuteFrequency;
      return response(url.pathname.endsWith("/minute-indicators") ? makeIndicatorsResponse(freq) : makeBarsResponse(freq));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result, rerender } = renderHook((props: { period: "day" | "m1" | "m5" }) => useIndexMinuteSeries({
      activePeriod: props.period,
      enabled: true,
      endDate: "2026-07-31",
      tsCode: "000001.SH",
    }), { initialProps: { period: "m1" } });

    await waitFor(() => expect(result.current.phase).toBe("ready"));
    expect(result.current.data?.indicatorSource).toBe("gold");
    rerender({ period: "m5" });
    await waitFor(() => expect(result.current.data?.freq).toBe(5));
    rerender({ period: "day" });
    expect(result.current.phase).toBe("idle");
    rerender({ period: "m1" });
    await waitFor(() => expect(result.current.data?.freq).toBe(1));

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/minute-indicators"))).toHaveLength(2);
    expect(fetchMock.mock.calls.filter(([input]) => String(input).includes("/index-detail/minutes"))).toHaveLength(2);
  });

  it("does not let older bars or indicators overwrite the current frequency", async () => {
    const pendingOneMinute: Array<{ input: string; resolve: (value: Response) => void }> = [];
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      const freq = Number(url.searchParams.get("freq")) as IndexDetailMinuteFrequency;
      if (freq === 1) {
        return new Promise<Response>((resolve) => pendingOneMinute.push({ input: url.pathname, resolve }));
      }
      return response(url.pathname.endsWith("/minute-indicators") ? makeIndicatorsResponse(freq) : makeBarsResponse(freq));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result, rerender } = renderHook((props: { period: "m1" | "m5" }) => useIndexMinuteSeries({
      activePeriod: props.period,
      enabled: true,
      endDate: "2026-07-31",
      tsCode: "000001.SH",
    }), { initialProps: { period: "m1" } });

    rerender({ period: "m5" });
    await waitFor(() => expect(result.current.data?.freq).toBe(5));
    await act(async () => {
      pendingOneMinute.forEach(({ input, resolve }) => resolve(response(
        input.endsWith("/minute-indicators") ? makeIndicatorsResponse(1) : makeBarsResponse(1),
      )));
    });
    expect(result.current.data?.freq).toBe(5);
  });

  it("renders bars before the indicator request settles", async () => {
    let resolveIndicators: ((value: Response) => void) | undefined;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      if (url.pathname.endsWith("/minute-indicators")) {
        return new Promise<Response>((resolve) => { resolveIndicators = resolve; });
      }
      return response(makeBarsResponse(1));
    }));

    const { result } = renderHook(() => useIndexMinuteSeries({
      activePeriod: "m1",
      enabled: true,
      endDate: "2026-07-31",
      tsCode: "000001.SH",
    }));

    await waitFor(() => expect(result.current.data?.points).toHaveLength(20));
    expect(result.current.phase).toBe("loading");
    expect(result.current.data?.indicatorSource).toBe("unavailable");

    await act(async () => { resolveIndicators?.(response(makeIndicatorsResponse(1))); });
    await waitFor(() => expect(result.current.phase).toBe("ready"));
    expect(result.current.data?.indicatorSource).toBe("gold");
  });

  it("keeps real bars and marks only the indicator layer partial when Gold fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      if (url.pathname.endsWith("/minute-indicators")) {
        return response({ code: "IM_QUERY_FAILED", message: "指标查询失败" }, 500);
      }
      return response(makeBarsResponse(1));
    }));

    const { result } = renderHook(() => useIndexMinuteSeries({
      activePeriod: "m1",
      enabled: true,
      endDate: "2026-07-31",
      tsCode: "000001.SH",
    }));

    await waitFor(() => expect(result.current.phase).toBe("partial"));
    expect(result.current.data?.points).toHaveLength(20);
    expect(result.current.data?.indicatorSource).toBe("unavailable");
    expect(result.current.data?.points.every((point) => point.ma5 === null && point.macd === null)).toBe(true);
    expect(result.current.errorMessage).toContain("K 线仍可使用");
  });

  it("keeps the Beijing index source gap as a local empty state", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      if (url.pathname.endsWith("/minute-indicators")) {
        return response(makeIndicatorsResponse(1, true));
      }
      return response(makeBarsResponse(1, true));
    }));
    const { result } = renderHook(() => useIndexMinuteSeries({
      activePeriod: "m1",
      enabled: true,
      endDate: "2026-07-31",
      tsCode: "899050.BJ",
    }));

    await waitFor(() => expect(result.current.phase).toBe("empty"));
    expect(result.current.data).toBeNull();
    expect(result.current.errorMessage).toContain("不覆盖");
  });
});

function makeBarsResponse(freq: IndexDetailMinuteFrequency, empty = false): IndexMinutesResponseDto {
  const bars = empty ? [] : Array.from({ length: 20 }, (_, index) => ({
    tsCode: "000001.SH",
    freq,
    tradeDate: "2026-07-31",
    tradeTime: `2026-07-31T${String(9 + Math.floor((30 + index) / 60)).padStart(2, "0")}:${String((30 + index) % 60).padStart(2, "0")}:00+08:00`,
    open: 10 + index,
    high: 11 + index,
    low: 9 + index,
    close: 10.5 + index,
    vol: 100 + index,
    amount: 1000 + index,
    exchange: "SSE",
  })).reverse();
  return {
    tsCode: empty ? "899050.BJ" : "000001.SH",
    freq,
    bars,
    meta: { count: bars.length, limit: 500, hasMore: false, nextCursor: null, startDate: null, endDate: "2026-07-31", observedStartDate: empty ? null : "2026-07-31", observedEndDate: empty ? null : "2026-07-31" },
    dataStatus: empty
      ? { status: "EMPTY", code: "IM_SOURCE_NOT_READY", expectedEndDate: "2026-07-31", observedEndDate: null, message: "当前分钟数据源暂不覆盖该指数。" }
      : { status: "READY", code: null, expectedEndDate: "2026-07-31", observedEndDate: "2026-07-31", message: null },
  };
}

function makeIndicatorsResponse(freq: IndexDetailMinuteFrequency, empty = false): IndexMinuteIndicatorsResponseDto {
  const bars = makeBarsResponse(freq, empty);
  const items = bars.bars.map((bar, index) => ({
    tsCode: bar.tsCode,
    freq: bar.freq,
    tradeDate: bar.tradeDate,
    tradeTime: bar.tradeTime,
    ma5: 10 + index,
    ma10: null,
    ma20: null,
    ma30: null,
    ma60: null,
    ma90: null,
    ma250: null,
    bollMiddle: null,
    bollUpper: null,
    bollLower: null,
    macdDif: 0.1,
    macdDea: 0.05,
    macd: 0.1,
    kdjK: 50,
    kdjD: 45,
    kdjJ: 60,
    observationCount: index + 1,
    paramsKey: PARAMS_KEY,
    indicatorVersion: 1,
  }));
  return {
    tsCode: bars.tsCode,
    freq,
    items,
    meta: { ...bars.meta, count: items.length },
    dataStatus: bars.dataStatus,
  };
}

function response(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}
