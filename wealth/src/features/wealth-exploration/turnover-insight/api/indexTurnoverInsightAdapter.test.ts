import { describe, expect, it } from "vitest";

import type { IndexTurnoverInsightPanelResponse, IndexTurnoverInsightResponse } from "./indexTurnoverInsightApi";
import { buildIndexTurnoverInsightViewModelFromApi } from "./indexTurnoverInsightAdapter";

function panel(index: number): IndexTurnoverInsightPanelResponse {
  const amount = { amountYi: index, displayText: `${index}亿`, direction: "neutral" as const };
  return {
    tsCode: `${String(index).padStart(6, "0")}.SH`,
    indexName: `指数${index}`,
    status: "READY",
    summary: {
      current: amount,
      previous: amount,
      delta: amount,
      avg5d: { ...amount, referenceLabel: `5日均值 ${index}亿` },
      avg20d: { ...amount, referenceLabel: `20日均值 ${index}亿` },
    },
    upperAxis: { minYi: 0, maxYi: 10, zeroYi: 0, ticks: [] },
    deltaAxis: { minYi: -1, maxYi: 1, zeroYi: 0, ticks: [] },
    series: [],
    message: null,
    exceptionCode: null,
  };
}

function payload(indices = Array.from({ length: 10 }, (_, index) => panel(9 - index))): IndexTurnoverInsightResponse {
  return {
    status: "READY",
    tradingDay: {
      market: "CN_A",
      expectedTradeDate: "2026-09-01",
      observedTradeDate: "2026-09-01",
      previousObservedTradeDate: "2026-08-31",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: "2026-09-02T08:00:00+08:00",
    },
    asOf: "盘后数据 · 2026-09-01",
    unit: "yi",
    unitLabel: "亿",
    indices,
    message: null,
    exceptionCode: null,
    debugInfo: null,
  };
}

describe("indexTurnoverInsightAdapter", () => {
  it("preserves the backend identity order without calculating or sorting", () => {
    const model = buildIndexTurnoverInsightViewModelFromApi(payload());

    expect(model.indices.map((item) => item.indexName)).toEqual([
      "指数9", "指数8", "指数7", "指数6", "指数5",
      "指数4", "指数3", "指数2", "指数1", "指数0",
    ]);
    expect(model.indices[0]?.summary.current.displayText).toBe("9亿");
    expect(model.asOf).toBe("盘后数据 · 2026-09-01");
  });

  it("rejects missing or duplicate cards instead of constructing placeholders", () => {
    expect(() => buildIndexTurnoverInsightViewModelFromApi(payload([panel(1)]))).toThrow("固定 10 项");
    expect(() => buildIndexTurnoverInsightViewModelFromApi(payload(Array.from({ length: 10 }, () => panel(1))))).toThrow("身份重复");
  });
});
