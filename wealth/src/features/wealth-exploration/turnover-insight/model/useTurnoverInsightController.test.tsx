import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TurnoverInsightResponse } from "../api/turnoverInsightApi";
import { useTurnoverInsightController } from "./useTurnoverInsightController";

const { fetchTurnoverInsightMock } = vi.hoisted(() => ({
  fetchTurnoverInsightMock: vi.fn(),
}));

vi.mock("../api/turnoverInsightApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/turnoverInsightApi")>();
  return { ...actual, fetchTurnoverInsight: fetchTurnoverInsightMock };
});

function emptyPayload(tradeDate: string): TurnoverInsightResponse {
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
      generatedAt: `${tradeDate}T15:05:00+08:00`,
    },
    asOf: null,
    unit: "yi",
    unitLabel: "亿",
    summary: {
      current: { amountYi: null, displayText: "--", direction: "neutral" },
      previous: { amountYi: null, displayText: "--", direction: "neutral" },
      delta: { amountYi: null, displayText: "--", direction: "neutral" },
      avg5d: { amountYi: null, displayText: "--", direction: "neutral", referenceLabel: "5日均值 --" },
      avg20d: { amountYi: null, displayText: "--", direction: "neutral", referenceLabel: "20日均值 --" },
    },
    upperAxis: null,
    deltaAxis: null,
    series: [],
    message: "暂无数据",
    exceptionCode: "TI_CURRENT_SNAPSHOT_MISSING",
    debugInfo: null,
  };
}

beforeEach(() => {
  fetchTurnoverInsightMock.mockReset();
});

describe("useTurnoverInsightController", () => {
  it("aborts the stale date request before loading the next date", async () => {
    const first = new Promise<TurnoverInsightResponse>(() => undefined);
    fetchTurnoverInsightMock
      .mockReturnValueOnce(first)
      .mockResolvedValueOnce(emptyPayload("2026-08-21"));
    const { rerender, result } = renderHook(
      ({ tradeDate }) => useTurnoverInsightController({ market: "CN_A", tradeDate }),
      { initialProps: { tradeDate: "2026-08-20" } },
    );
    const firstSignal = fetchTurnoverInsightMock.mock.calls[0][1].signal as AbortSignal;

    rerender({ tradeDate: "2026-08-21" });

    expect(firstSignal.aborted).toBe(true);
    await waitFor(() => expect(result.current.viewState).toBe("empty"));
    expect(result.current.model?.tradingDay.expectedTradeDate).toBe("2026-08-21");
    expect(fetchTurnoverInsightMock).toHaveBeenCalledTimes(2);
  });

  it("retries only the current turnover request", async () => {
    fetchTurnoverInsightMock.mockResolvedValue(emptyPayload("2026-08-21"));
    const { result } = renderHook(() => useTurnoverInsightController({
      market: "CN_A",
      tradeDate: "2026-08-21",
    }));
    await waitFor(() => expect(result.current.viewState).toBe("empty"));

    act(() => result.current.retry());

    await waitFor(() => expect(fetchTurnoverInsightMock).toHaveBeenCalledTimes(2));
  });
});
