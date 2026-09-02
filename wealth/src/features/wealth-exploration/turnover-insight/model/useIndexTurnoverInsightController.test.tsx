import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { IndexTurnoverInsightResponse } from "../api/indexTurnoverInsightApi";
import { useIndexTurnoverInsightController } from "./useIndexTurnoverInsightController";

function payload(tradeDate = "2026-09-01"): IndexTurnoverInsightResponse {
  const amount = { amountYi: null, displayText: "--", direction: "neutral" as const };
  const indices = Array.from({ length: 10 }, (_, index) => ({
    tsCode: `${String(index).padStart(6, "0")}.SH`,
    indexName: `指数${index}`,
    status: "EMPTY" as const,
    summary: {
      current: amount,
      previous: amount,
      delta: amount,
      avg5d: { ...amount, referenceLabel: "5日均值 --" },
      avg20d: { ...amount, referenceLabel: "20日均值 --" },
    },
    upperAxis: null,
    deltaAxis: null,
    series: [],
    message: "暂无数据",
    exceptionCode: "ITI_SOURCE_NOT_READY",
  }));
  return {
    status: "EMPTY",
    tradingDay: {
      market: "CN_A",
      expectedTradeDate: tradeDate,
      observedTradeDate: null,
      previousObservedTradeDate: null,
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: `${tradeDate}T16:00:00+08:00`,
    },
    asOf: null,
    unit: "yi",
    unitLabel: "亿",
    indices,
    message: "暂无数据",
    exceptionCode: "ITI_SOURCE_NOT_READY",
    debugInfo: null,
  };
}

function response(payloadValue: unknown, status = 200): Response {
  return new Response(JSON.stringify(payloadValue), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("useIndexTurnoverInsightController", () => {
  it("hides only a real endpoint 404", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ message: "not found", code: "not_found" }, 404)));
    const { result } = renderHook(() => useIndexTurnoverInsightController({
      market: "CN_A", tradeDate: "2026-09-01",
    }));

    await waitFor(() => expect(result.current.capabilityState).toBe("unsupported"));
    expect(result.current.model).toBeNull();
    expect(result.current.errorMessage).toBeNull();
  });

  it("keeps 503 and other failures visible as a supported capability error", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({
      message: "not ready", code: "ITI_SOURCE_NOT_READY",
    }, 503)));
    const { result } = renderHook(() => useIndexTurnoverInsightController({
      market: "CN_A", tradeDate: "2026-09-01",
    }));

    await waitFor(() => expect(result.current.viewState).toBe("error"));
    expect(result.current.capabilityState).toBe("supported");
    expect(result.current.errorMessage).toBe("not ready");
  });

  it("cancels stale dates and retries one batch request", async () => {
    const fetchMock = vi.fn()
      .mockReturnValueOnce(new Promise(() => undefined))
      .mockResolvedValue(response(payload("2026-09-02")));
    vi.stubGlobal("fetch", fetchMock);
    const { rerender, result } = renderHook(
      ({ tradeDate }) => useIndexTurnoverInsightController({ market: "CN_A", tradeDate }),
      { initialProps: { tradeDate: "2026-09-01" } },
    );
    const firstSignal = fetchMock.mock.calls[0][1].signal as AbortSignal;
    rerender({ tradeDate: "2026-09-02" });

    expect(firstSignal.aborted).toBe(true);
    await waitFor(() => expect(result.current.viewState).toBe("empty"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
    act(() => result.current.retry());
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  });
});
