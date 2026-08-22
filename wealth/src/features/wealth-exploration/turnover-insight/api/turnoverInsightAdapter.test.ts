import { describe, expect, it } from "vitest";

import type { TurnoverInsightResponse } from "./turnoverInsightApi";
import { buildTurnoverInsightViewModelFromApi } from "./turnoverInsightAdapter";

function payload(): TurnoverInsightResponse {
  return {
    status: "READY",
    tradingDay: {
      market: "CN_A",
      expectedTradeDate: "2026-08-21",
      observedTradeDate: "2026-08-21",
      previousObservedTradeDate: "2026-08-20",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: "2026-08-22T20:00:00+08:00",
    },
    asOf: "2026-08-22T20:00:00+08:00",
    unit: "yi",
    unitLabel: "亿",
    summary: {
      current: { amountYi: 18921, displayText: "18,921亿", direction: "neutral" },
      previous: { amountYi: 20939, displayText: "20,939亿", direction: "neutral" },
      delta: { amountYi: -2018, displayText: "-2,018亿", direction: "down" },
      avg5d: {
        amountYi: 23771,
        displayText: "23,771亿",
        direction: "neutral",
        referenceLabel: "5日均值 23,771亿",
      },
      avg20d: {
        amountYi: 28064,
        displayText: "28,064亿",
        direction: "neutral",
        referenceLabel: "20日均值 28,064亿",
      },
    },
    upperAxis: {
      minYi: 0,
      maxYi: 32000,
      zeroYi: 0,
      ticks: [{ valueYi: 0, displayText: "0" }],
    },
    deltaAxis: {
      minYi: -2400,
      maxYi: 0,
      zeroYi: 0,
      ticks: [{ valueYi: 0, displayText: "0" }],
    },
    series: [],
    message: null,
    exceptionCode: null,
  };
}

describe("buildTurnoverInsightViewModelFromApi", () => {
  it("copies backend daily averages and reference labels without recomputing them", () => {
    const model = buildTurnoverInsightViewModelFromApi(payload());

    expect(model.summary.avg5d).toEqual({
      amountYi: 23771,
      displayText: "23,771亿",
      direction: "neutral",
      referenceLabel: "5日均值 23,771亿",
    });
    expect(model.summary.avg20d.referenceLabel).toBe("20日均值 28,064亿");
  });
});
