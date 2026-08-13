import { describe, expect, it } from "vitest";

import type {
  StockMinuteBarsResponseDto,
  StockMinuteIndicatorsResponseDto,
} from "./stockMinuteApiTypes";
import { buildStockMinuteChartViewModel, minuteFrequencyFromPeriodKey } from "./stockMinuteViewModelAdapter";

function status(status: "READY" | "DELAYED" | "EMPTY" | "ERROR") {
  return { status, expectedEndDate: "2026-07-31", observedEndDate: "2026-07-31", message: null };
}

function bars(): StockMinuteBarsResponseDto {
  return {
    tsCode: "000638.SZ",
    freq: 5,
    bars: [
      {
        tsCode: "000638.SZ",
        freq: 5,
        tradeDate: "2026-07-30",
        tradeTime: "2026-07-30T09:35:00+08:00",
        open: 1,
        high: 2,
        low: 0.5,
        close: 1.5,
        vol: 10,
        amount: 100,
        exchange: "SZSE",
      },
      {
        tsCode: "000638.SZ",
        freq: 5,
        tradeDate: "2026-07-31",
        tradeTime: "2026-07-31T09:35:00+08:00",
        open: 1.5,
        high: 2.5,
        low: 1,
        close: 2,
        vol: 11,
        amount: 110,
        exchange: "SZSE",
      },
    ],
    meta: { count: 2, limit: 500, hasMore: false },
    dataStatus: status("READY"),
  };
}

function indicators(): StockMinuteIndicatorsResponseDto {
  return {
    tsCode: "000638.SZ",
    freq: 5,
    items: [
      {
        tsCode: "000638.SZ",
        freq: 5,
        tradeDate: "2026-07-30",
        tradeTime: "2026-07-30T09:35:00+08:00",
        macdDif: null,
        macdDea: null,
        macd: null,
        kdjK: 1,
        kdjD: 2,
        kdjJ: 3,
        paramsKey: "macd_12_26_9__kdj_9_3_3",
        indicatorVersion: 1,
      },
      {
        tsCode: "000638.SZ",
        freq: 5,
        tradeDate: "2026-07-31",
        tradeTime: "2026-07-31T09:35:00+08:00",
        macdDif: 0.1,
        macdDea: 0.05,
        macd: 0.1,
        kdjK: null,
        kdjD: null,
        kdjJ: null,
        paramsKey: "macd_12_26_9__kdj_9_3_3",
        indicatorVersion: 1,
      },
    ],
    meta: { count: 2, limit: 500, hasMore: false },
    dataStatus: status("READY"),
  };
}

describe("stock minute view model adapter", () => {
  it("merges exact full date-time keys and preserves warmup nulls", () => {
    const viewModel = buildStockMinuteChartViewModel(bars(), indicators());

    expect(viewModel.points).toHaveLength(2);
    expect(viewModel.points[0]).toMatchObject({
      key: "2026-07-30T09:35:00+08:00",
      macdDif: null,
      kdjJ: 3,
    });
    expect(viewModel.points[1]).toMatchObject({
      key: "2026-07-31T09:35:00+08:00",
      macdDif: 0.1,
      kdjK: null,
    });
  });

  it("rejects missing or extra indicator time keys", () => {
    const missing = indicators();
    missing.items = missing.items.slice(0, 1);
    expect(() => buildStockMinuteChartViewModel(bars(), missing)).toThrow("时间键不一致");

    const extra = indicators();
    extra.items.push({ ...extra.items[1]!, tradeDate: "2026-08-01", tradeTime: "2026-08-01T09:35:00+08:00" });
    expect(() => buildStockMinuteChartViewModel(bars(), extra)).toThrow("时间键不一致");
  });

  it("rejects response identity drift and duplicate time keys", () => {
    const wrongIdentity = indicators();
    wrongIdentity.freq = 15;
    expect(() => buildStockMinuteChartViewModel(bars(), wrongIdentity)).toThrow("身份不一致");

    const duplicated = indicators();
    duplicated.items.push({ ...duplicated.items[0]! });
    expect(() => buildStockMinuteChartViewModel(bars(), duplicated)).toThrow("重复时间键");
  });

  it("maps all supported minute period keys and rejects non-minute keys", () => {
    expect(["m1", "m5", "m15", "m30", "m60", "m90", "m120"].map(minuteFrequencyFromPeriodKey)).toEqual([
      1, 5, 15, 30, 60, 90, 120,
    ]);
    expect(minuteFrequencyFromPeriodKey("day")).toBeNull();
    expect(minuteFrequencyFromPeriodKey("m2")).toBeNull();
  });
});
