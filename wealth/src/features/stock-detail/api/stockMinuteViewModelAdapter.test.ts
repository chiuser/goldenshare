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
        tradeTime: "2026-07-30T09:30:00+08:00",
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
        tradeTime: "2026-07-31T09:30:00+08:00",
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
        tradeTime: "2026-07-30T09:30:00+08:00",
        macdDif: null,
        macdDea: null,
        macd: null,
        kdjK: 1,
        kdjD: 2,
        kdjJ: 3,
        paramsKey: "macd_12_26_9__kdj_9_3_3",
        indicatorVersion: 1,
      },
    ],
    meta: { count: 1, limit: 500, hasMore: false },
    dataStatus: status("READY"),
  };
}

describe("stock minute view model adapter", () => {
  it("merges by full date-time key and preserves missing indicators as null", () => {
    const viewModel = buildStockMinuteChartViewModel(bars(), indicators());

    expect(viewModel.points).toHaveLength(2);
    expect(viewModel.points[0]).toMatchObject({
      key: "2026-07-30T09:30:00+08:00",
      macdDif: null,
      kdjJ: 3,
    });
    expect(viewModel.points[1]).toMatchObject({
      key: "2026-07-31T09:30:00+08:00",
      macdDif: null,
      kdjK: null,
    });
  });

  it("maps all supported minute period keys and rejects non-minute keys", () => {
    expect(["m1", "m5", "m15", "m30", "m60", "m90", "m120"].map(minuteFrequencyFromPeriodKey)).toEqual([
      1, 5, 15, 30, 60, 90, 120,
    ]);
    expect(minuteFrequencyFromPeriodKey("day")).toBeNull();
    expect(minuteFrequencyFromPeriodKey("m2")).toBeNull();
  });
});
