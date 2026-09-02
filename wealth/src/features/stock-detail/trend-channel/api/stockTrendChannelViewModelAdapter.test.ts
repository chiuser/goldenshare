import { describe, expect, it } from "vitest";

import type { StockTrendChannelResponseDto } from "./stockTrendChannelApiTypes";
import { buildStockTrendChannelViewModel } from "./stockTrendChannelViewModelAdapter";

describe("buildStockTrendChannelViewModel", () => {
  it("preserves the API array order without sorting or recomputing", () => {
    const payload = makePayload();
    const result = buildStockTrendChannelViewModel(payload);

    expect(result.points.map((point) => point.time)).toEqual(["2026-08-25", "2026-08-27"]);
    expect(result.points[0]).toEqual({
      time: "2026-08-25",
      close: 10.5,
      shortUpper: 12,
      shortLower: 9.5,
      longUpper: 13,
      longLower: 8.5,
    });
  });

  it("rejects out-of-order input instead of sorting it in the frontend", () => {
    const payload = makePayload();
    payload.bars.reverse();
    expect(() => buildStockTrendChannelViewModel(payload)).toThrow("严格按交易日升序");
  });
});

function makePayload(): StockTrendChannelResponseDto {
  return {
    stockRef: { tsCode: "000001.SZ", name: "平安银行" },
    period: "day",
    adjustment: "forward",
    sourceAdjustment: "qfq",
    formula: {
      key: "high-low-ema-hysteresis",
      version: "stock-daily-trend-channel-v1",
      shortPeriod: 25,
      longPeriod: 90,
      seed: "first_observation",
      stateRule: "strict_close_breakout_inside_retention",
    },
    bars: ["2026-08-25", "2026-08-27"].map((tradeDate) => ({
      tradeDate,
      open: 10,
      high: 11,
      low: 9,
      close: 10.5,
      shortChannel: { upper: 12, lower: 9.5, position: "INSIDE", state: "UP" },
      longChannel: { upper: 13, lower: 8.5, position: "INSIDE", state: "DOWN" },
      combinedState: "UP_DOWN",
    })),
    meta: { count: 2, limit: 300, endDate: "2026-08-27" },
    dataStatus: { status: "READY", observedTradeDate: "2026-08-27", note: null },
  };
}
