import { describe, expect, it } from "vitest";

import type { StockDetailKlineResponseDto, StockDetailPageInitResponseDto } from "./stockDetailApiTypes";
import { getStockDetailViewModel } from "./stockDetailMockAdapter";
import { buildStockDetailViewModel } from "./stockDetailViewModelAdapter";

describe("buildStockDetailViewModel", () => {
  it("preserves unavailable moving averages as null instead of synthesizing zero", () => {
    const viewModel = buildStockDetailViewModel(makePageInit(), makeKline());
    const point = viewModel.chart.candles[0]!;

    expect(point.ma5).toBeNull();
    expect(point.ma10).toBe(0);
    expect(point.ma20).toBe(18.2);
    expect(point.ma30).toBeNull();
    expect(point.ma60).toBeNull();
    expect(point.ma90).toBeNull();
    expect(point.ma250).toBeNull();
    expect(point.volumeDisplay).toBe("10.00万");
  });

  it("preserves unavailable MACD and KDJ values as null and uses backend volume display", () => {
    const pageInit = makePageInit();
    const kline = makeKline();
    kline.bars[0].factors.macd = { dif: null, dea: null, macd: null };
    kline.bars[0].factors.kdj = { k: null, d: null, j: null };

    const viewModel = buildStockDetailViewModel(pageInit, kline);
    const point = viewModel.chart.candles[0]!;

    expect(viewModel.quote.volumeText).toBe("10.00万");
    expect([point.macd, point.dif, point.dea, point.k, point.d, point.j]).toEqual([
      null, null, null, null, null, null,
    ]);
  });

  it("keeps mock moving averages empty until the full observation window exists", () => {
    const candles = getStockDetailViewModel("688635.SH").chart.candles;

    expect(candles.slice(0, 4).every((point) => point.ma5 === null)).toBe(true);
    expect(candles[4]!.ma5).not.toBeNull();
    expect(candles.slice(0, 9).every((point) => point.ma10 === null)).toBe(true);
    expect(candles[9]!.ma10).not.toBeNull();
    expect(candles.slice(0, 89).every((point) => point.ma90 === null)).toBe(true);
    expect(candles[89]!.ma90).not.toBeNull();
    expect(candles.every((point) => point.ma250 === null)).toBe(true);
  });
});

function makePageInit(): StockDetailPageInitResponseDto {
  return {
    pageContext: {
      market: "CN_A",
      tradeDate: "2026-08-14",
      prevTradeDate: "2026-08-13",
      isTradingDay: true,
      sessionStatus: "CLOSED",
      timezone: "Asia/Shanghai",
      generatedAt: "2026-08-14T20:00:00+08:00",
      source: "explicit",
    },
    stock: {
      tsCode: "688635.SH",
      name: "长进光子",
      market: "科创板",
      exchange: "SSE",
      industry: "通信设备",
      tags: ["通信设备"],
    },
    quote: {
      tradeDate: "2026-08-14",
      price: 300,
      change: 10,
      changePct: 3.45,
      direction: "UP",
      open: 292,
      high: 310,
      low: 288,
      close: 300,
      preClose: 290,
      turnoverRate: 5,
      volumeRatio: 1.2,
      vol: 100_000,
      volDisplay: "10.00万",
      amount: 30_000_000,
    },
    chartDefaults: {
      defaultPeriod: "day",
      defaultAdjustment: "forward",
      sourceAdjustment: "qfq",
      availablePeriods: ["day"],
      availableAdjustments: ["forward"],
      availableMainOverlays: ["MA", "BOLL"],
      availableIndicatorTabs: ["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"],
    },
    capabilities: {
      supportsRealtime: false,
      supportsMinute: false,
      minuteFrequencies: [],
      supportsNineTurn: false,
      supportsTrendChannel: false,
      nineTurnPeriods: ["day"],
      supportsWeeklyMonthly: false,
      userActions: { watchlist: true, alert: false, tradePlan: false, diagnosis: false },
    },
    dataStatus: {
      status: "READY",
      expectedTradeDate: "2026-08-14",
      observedTradeDate: "2026-08-14",
    },
  };
}

function makeKline(): StockDetailKlineResponseDto {
  const pageContext = makePageInit().pageContext;
  return {
    pageContext,
    stockRef: { tsCode: "688635.SH", name: "长进光子" },
    period: "day",
    adjustment: "forward",
    sourceAdjustment: "qfq",
    bars: [{
      tradeDate: "2026-08-14",
      open: 292,
      high: 310,
      low: 288,
      close: 300,
      preClose: 290,
      change: 10,
      changePct: 3.45,
      amplitude: 7.59,
      vol: 100_000,
      volDisplay: "10.00万",
      amount: 30_000_000,
      turnoverRate: 5,
      volumeRatio: 1.2,
      factors: {
        ma: {
          ma5: null,
          ma10: 0,
          ma20: 18.2,
          ma30: undefined,
          ma60: null,
          ma90: null,
          ma250: null,
        },
        boll: { upper: null, middle: null, lower: null },
        macd: { dif: 0.1, dea: 0.2, macd: -0.2 },
        kdj: { k: 50, d: 45, j: 60 },
      },
    }],
    meta: { count: 1, limit: 300, endDate: "2026-08-14" },
    dataStatus: {
      status: "READY",
      expectedTradeDate: "2026-08-14",
      observedTradeDate: "2026-08-14",
    },
  };
}
