import { describe, expect, it } from "vitest";

import { buildMarketPageContextViewModelFromApi } from "./marketPageContextAdapter";

describe("marketPageContextAdapter", () => {
  it("preserves the complete shared market time contract", () => {
    const model = buildMarketPageContextViewModelFromApi({
      pageContext: {
        market: "CN_A",
        tradeDate: "2026-08-21",
        prevTradeDate: "2026-08-20",
        isTradingDay: true,
        sessionStatus: "CLOSED",
        timezone: "Asia/Shanghai",
        generatedAt: "2026-08-22T09:15:30+08:00",
        source: "explicit",
      },
    });

    expect(model).toEqual({
      market: "CN_A",
      tradeDate: "2026-08-21",
      prevTradeDate: "2026-08-20",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: "2026-08-22T09:15:30+08:00",
      updateTime: "2026-08-22 09:15:30",
      source: "explicit",
    });
  });
});
