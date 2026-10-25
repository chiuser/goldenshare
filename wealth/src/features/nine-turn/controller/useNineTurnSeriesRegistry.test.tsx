import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { NineTurnPeriod, NineTurnSeriesDto } from "../api/nineTurnApiTypes";
import type { NineTurnSeriesLoader } from "./useNineTurnSeriesRegistry";
import { useNineTurnSeriesRegistry } from "./useNineTurnSeriesRegistry";

describe("useNineTurnSeriesRegistry", () => {
  it("never requests an unsupported stock period", async () => {
    const load = vi.fn<NineTurnSeriesLoader>();
    const { result } = renderHook(() => useNineTurnSeriesRegistry({
      endDate: "2026-08-13",
      load,
      subjectType: "stock",
      supportedPeriods: ["day", "30"],
      supportsNineTurn: true,
      tsCode: "000001.SZ",
    }));

    await act(() => result.current.ensure("5"));

    expect(load).not.toHaveBeenCalled();
    expect(result.current.stateFor("5").phase).toBe("UNSUPPORTED");
  });

  it("caches ready data by the complete period key", async () => {
    const load = vi.fn<NineTurnSeriesLoader>().mockResolvedValue(response("day"));
    const { result } = renderHook(() => useNineTurnSeriesRegistry({
      endDate: "2026-08-13",
      load,
      subjectType: "stock",
      supportedPeriods: ["day"],
      supportsNineTurn: true,
      tsCode: "000001.SZ",
    }));

    await act(() => result.current.ensure("day"));
    await waitFor(() => expect(result.current.stateFor("day").phase).toBe("READY"));
    await act(() => result.current.ensure("day"));

    expect(load).toHaveBeenCalledTimes(1);
    expect(load.mock.calls[0]?.[0]).toEqual({
      endDate: "2026-08-13",
      limit: 300,
      period: "day",
      subjectType: "stock",
      tsCode: "000001.SZ",
    });
  });

  it("loads different period keys concurrently without aborting either request", async () => {
    const deferred = new Map<NineTurnPeriod, PromiseController<NineTurnSeriesDto>>();
    const load = vi.fn<NineTurnSeriesLoader>((request) => {
      const pending = promiseController<NineTurnSeriesDto>();
      deferred.set(request.period, pending);
      return pending.promise;
    });
    const { result } = renderHook(() => useNineTurnSeriesRegistry({
      endDate: "2026-08-13",
      load,
      subjectType: "stock",
      supportedPeriods: ["day", "30"],
      supportsNineTurn: true,
      tsCode: "000001.SZ",
    }));

    let dayPromise: Promise<void>;
    let minutePromise: Promise<void>;
    act(() => {
      dayPromise = result.current.ensure("day");
    });
    const daySignal = load.mock.calls[0]?.[1].signal;
    act(() => {
      minutePromise = result.current.ensure("30");
    });
    const minuteSignal = load.mock.calls[1]?.[1].signal;
    expect(daySignal?.aborted).toBe(false);
    expect(minuteSignal?.aborted).toBe(false);
    await act(async () => {
      deferred.get("day")?.resolve(response("day"));
      deferred.get("30")?.resolve(response("30"));
      await Promise.all([dayPromise!, minutePromise!]);
    });

    expect(result.current.stateFor("day").phase).toBe("READY");
    expect(result.current.stateFor("30").phase).toBe("READY");
  });

  it("does not retry an error until retry is explicitly requested", async () => {
    const load = vi.fn<NineTurnSeriesLoader>()
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce(response("day"));
    const { result } = renderHook(() => useNineTurnSeriesRegistry({
      endDate: "2026-08-13",
      load,
      subjectType: "stock",
      supportedPeriods: ["day"],
      supportsNineTurn: true,
      tsCode: "000001.SZ",
    }));

    await act(() => result.current.ensure("day"));
    await waitFor(() => expect(result.current.stateFor("day").phase).toBe("ERROR"));
    await act(() => result.current.ensure("day"));
    expect(load).toHaveBeenCalledTimes(1);

    await act(() => result.current.retry("day"));
    await waitFor(() => expect(result.current.stateFor("day").phase).toBe("READY"));
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("uses the index daily limit while minute requests remain 500", async () => {
    const load = vi.fn<NineTurnSeriesLoader>().mockImplementation(async ({ period, limit }) => ({
      ...response(period), meta: { ...response(period).meta, limit },
      subjectType: "index", tsCode: "000001.SH",
    }));
    const { result } = renderHook(() => useNineTurnSeriesRegistry({
      dailyLimit: 1000, endDate: "2026-08-13", load, subjectType: "index",
      supportedPeriods: ["day", "30"], supportsNineTurn: true, tsCode: "000001.SH",
    }));

    await act(() => result.current.ensure("day"));
    await act(() => result.current.ensure("30"));

    expect(load.mock.calls.map(([request]) => [request.period, request.limit])).toEqual([
      ["day", 1000], ["30", 500],
    ]);
    expect(result.current.stateFor("day").phase).toBe("READY");
    expect(result.current.stateFor("30").phase).toBe("READY");
  });

  it("drops the old daily request and its late response when the daily limit changes", async () => {
    const oldRequest = promiseController<NineTurnSeriesDto>();
    const load = vi.fn<NineTurnSeriesLoader>()
      .mockReturnValueOnce(oldRequest.promise)
      .mockResolvedValueOnce({ ...response("day"), meta: { ...response("day").meta, limit: 1000 } });
    const { result, rerender } = renderHook(({ dailyLimit }) => useNineTurnSeriesRegistry({
      dailyLimit, endDate: "2026-08-13", load, subjectType: "stock",
      supportedPeriods: ["day"], supportsNineTurn: true, tsCode: "000001.SZ",
    }), { initialProps: { dailyLimit: 300 } });

    let oldPromise: Promise<void>;
    act(() => { oldPromise = result.current.ensure("day"); });
    const oldSignal = load.mock.calls[0]![1].signal;
    rerender({ dailyLimit: 1000 });
    expect(oldSignal?.aborted).toBe(true);
    expect(result.current.stateFor("day").phase).toBe("IDLE");

    await act(() => result.current.ensure("day"));
    expect(load.mock.calls[1]![0].limit).toBe(1000);
    await act(async () => {
      oldRequest.resolve({ ...response("day"), markers: [] });
      await oldPromise!;
    });
    expect(result.current.stateFor("day").markers).toHaveLength(1);
    expect(load).toHaveBeenCalledTimes(2);
    await act(() => result.current.ensure("day"));
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("keeps separate ordinary and research dates and retries only the requested instance", async () => {
    const load = vi.fn<NineTurnSeriesLoader>().mockImplementation(async ({ period, limit, endDate }) => {
      const payload = response(period);
      return { ...payload, subjectType: "index", tsCode: "000001.SH",
        latestMarker: { ...payload.latestMarker!, tradeDate: endDate },
        markers: payload.markers.map(marker => ({ ...marker, tradeDate: endDate })),
        dataStatus: { ...payload.dataStatus, expectedEndDate: endDate, observedEndDate: endDate },
        meta: { ...payload.meta, limit, endDate, observedEndDate: endDate, observedStartDate: endDate },
      };
    });
    const { result } = renderHook(() => {
      const common = { dailyLimit: 1000, load, subjectType: "index" as const,
        supportedPeriods: ["day"] as const, supportsNineTurn: true, tsCode: "000001.SH" };
      return {
        ordinary: useNineTurnSeriesRegistry({ ...common, endDate: "2026-08-13" }),
        research: useNineTurnSeriesRegistry({ ...common, endDate: "2026-08-12" }),
      };
    });
    await act(() => result.current.ordinary.ensure("day"));
    await act(() => result.current.research.ensure("day"));
    await act(() => result.current.research.retry("day"));
    expect(load.mock.calls.map(([request]) => [request.endDate, request.limit])).toEqual([
      ["2026-08-13", 1000], ["2026-08-12", 1000], ["2026-08-12", 1000],
    ]);
    expect(result.current.ordinary.stateFor("day").phase).toBe("READY");
  });
});

function response(period: NineTurnPeriod): NineTurnSeriesDto {
  const tradeTime = period === "day" ? null : "2026-08-13T10:00:00+08:00";
  return {
    dataStatus: {
      code: null,
      expectedEndDate: "2026-08-13",
      message: null,
      observedEndDate: "2026-08-13",
      status: "READY",
    },
    debugInfo: null,
    latestMarker: {
      completed: false,
      direction: "UP",
      sequenceNumber: 3,
      tradeDate: "2026-08-13",
      tradeTime,
    },
    markers: [{
      completed: false,
      direction: "UP",
      sequenceNumber: 3,
      tradeDate: "2026-08-13",
      tradeTime,
    }],
    meta: {
      comparisonLag: 4,
      endDate: "2026-08-13",
      formulaVersion: 1,
      hasMore: false,
      limit: period === "day" ? 300 : 500,
      markerCount: 1,
      matchedRowCount: 1,
      missingRowCount: 0,
      nextCursor: null,
      observedEndDate: "2026-08-13",
      observedStartDate: "2026-08-13",
      signalThreshold: 9,
      sourceRowCount: 1,
      startDate: null,
    },
    period,
    subjectType: "stock",
    tsCode: "000001.SZ",
  };
}

interface PromiseController<T> {
  promise: Promise<T>;
  reject: (reason?: unknown) => void;
  resolve: (value: T) => void;
}

function promiseController<T>(): PromiseController<T> {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}
