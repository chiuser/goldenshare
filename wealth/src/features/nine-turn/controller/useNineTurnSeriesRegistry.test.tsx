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

  it("aborts the previous period and ignores its late response", async () => {
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
    expect(daySignal?.aborted).toBe(true);
    await act(async () => {
      deferred.get("day")?.resolve(response("day"));
      deferred.get("30")?.resolve(response("30"));
      await Promise.all([dayPromise!, minutePromise!]);
    });

    expect(result.current.stateFor("day").phase).toBe("IDLE");
    expect(result.current.stateFor("30").phase).toBe("READY");
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
