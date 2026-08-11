import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IndexDetailMinuteFrequency, IndexMinutesResponseDto } from "../api/indexDetailApiTypes";
import { useIndexMinuteSeries } from "./useIndexMinuteSeries";

describe("useIndexMinuteSeries", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("caches each frequency independently and never calls the real indicator endpoint", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      return response(makeResponse(Number(url.searchParams.get("freq")) as IndexDetailMinuteFrequency));
    });
    vi.stubGlobal("fetch", fetchMock);
    const { result, rerender } = renderHook((props: { period: "day" | "m1" | "m5" }) => useIndexMinuteSeries({
      activePeriod: props.period,
      enabled: true,
      endDate: "2026-07-31",
      tsCode: "000001.SH",
    }), { initialProps: { period: "m1" } });

    await waitFor(() => expect(result.current.phase).toBe("ready"));
    expect(result.current.data?.indicatorSource).toBe("mock");
    rerender({ period: "m5" });
    await waitFor(() => expect(result.current.data?.freq).toBe(5));
    rerender({ period: "day" });
    expect(result.current.phase).toBe("idle");
    rerender({ period: "m1" });
    await waitFor(() => expect(result.current.data?.freq).toBe(1));

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes("minute-indicators"))).toBe(false);
  });

  it("does not let an older frequency response overwrite the current chart", async () => {
    let resolveOneMinute: ((value: Response) => void) | undefined;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = new URL(String(input));
      const freq = Number(url.searchParams.get("freq")) as IndexDetailMinuteFrequency;
      if (freq === 1) return new Promise<Response>((resolve) => { resolveOneMinute = resolve; });
      return response(makeResponse(freq));
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
    await act(async () => { resolveOneMinute?.(response(makeResponse(1))); });
    expect(result.current.data?.freq).toBe(5);
  });

  it("keeps the Beijing index source gap as a local empty state", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({
      ...makeResponse(1),
      bars: [],
      dataStatus: { status: "EMPTY", code: "IM_SOURCE_NOT_READY", expectedEndDate: "2026-07-31", observedEndDate: null, message: "当前分钟数据源暂不覆盖该指数。" },
    })));
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

function makeResponse(freq: IndexDetailMinuteFrequency): IndexMinutesResponseDto {
  return {
    tsCode: "000001.SH",
    freq,
    bars: Array.from({ length: 20 }, (_, index) => ({
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
    })).reverse(),
    meta: { count: 20, limit: 500, hasMore: false, nextCursor: null, startDate: null, endDate: "2026-07-31", observedStartDate: "2026-07-31", observedEndDate: "2026-07-31" },
    dataStatus: { status: "READY", code: null, expectedEndDate: "2026-07-31", observedEndDate: "2026-07-31", message: null },
  };
}

function response(payload: unknown): Response {
  return new Response(JSON.stringify(payload), { status: 200, headers: { "Content-Type": "application/json" } });
}
