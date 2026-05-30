import { describe, expect, it } from "vitest";

import { getStockDetailViewModel } from "./stockDetailMockAdapter";

describe("getStockDetailViewModel", () => {
  it("returns complete stock detail mock view model", () => {
    const viewModel = getStockDetailViewModel("603806.SH");

    expect(viewModel.stock.tsCode).toBe("603806.SH");
    expect(viewModel.topMarketTickers.length).toBeGreaterThanOrEqual(5);
    expect(viewModel.periods.map((period) => period.label)).toEqual([
      "分时",
      "日K",
      "周K",
      "月K",
      "120分",
      "90分",
      "60分",
      "30分",
      "15分",
      "5分",
      "1分",
    ]);
    expect(viewModel.chart.candles.length).toBeGreaterThan(100);
    expect(viewModel.rightRail.sectors).toHaveLength(4);
    expect(viewModel.rightRail.moneyFlow).toHaveLength(4);
  });
});
