import { describe, expect, it } from "vitest";

import type {
  IndexMinuteBarDto,
  IndexMinuteIndicatorDto,
  IndexMinuteIndicatorsResponseDto,
  IndexMinutesResponseDto,
} from "./indexDetailApiTypes";
import { buildIndexMinuteBarsOnlyViewModel, buildIndexMinuteChartViewModel } from "./indexMinuteViewModelAdapter";

const PARAMS_KEY = "ma_5_10_20_30_60_90_250__boll_20_2__macd_12_26_9__kdj_9_3_3";

describe("index minute Gold indicators", () => {
  it("sorts both responses, aligns time keys, and maps the frozen Gold fields", () => {
    const bars = makeBars(20);
    const indicators = makeIndicators(bars);
    const viewModel = buildIndexMinuteChartViewModel(
      makeBarsResponse([...bars].reverse()),
      makeIndicatorsResponse([...indicators].reverse()),
    );

    expect(viewModel.points[0]!.time).toBeLessThan(viewModel.points.at(-1)!.time);
    expect(viewModel.indicatorSource).toBe("gold");
    expect(viewModel.paramsKey).toBe(PARAMS_KEY);
    expect(viewModel.indicatorVersion).toBe(1);
    expect(viewModel.points[0]!.ma5).toBe(indicators[0]!.ma5);
    expect(viewModel.points[0]!.bollMiddle).toBe(indicators[0]!.bollMiddle);
    expect(viewModel.points[0]!.dif).toBe(indicators[0]!.macdDif);
    expect(viewModel.points[0]!.k).toBe(indicators[0]!.kdjK);
    expect(viewModel.points[0]!.preClose).toBeNull();
    expect(viewModel.points[0]!.changePct).toBeNull();
  });

  it("rejects an incomplete indicator time-key window", () => {
    const bars = makeBars(3);
    const indicators = makeIndicators(bars).slice(1);

    expect(() => buildIndexMinuteChartViewModel(
      makeBarsResponse(bars),
      makeIndicatorsResponse(indicators),
    )).toThrow("数量不一致");
  });

  it("rejects indicator identity drift", () => {
    const bars = makeBars(1);
    const response = makeIndicatorsResponse(makeIndicators(bars));
    response.tsCode = "399001.SZ";

    expect(() => buildIndexMinuteChartViewModel(makeBarsResponse(bars), response)).toThrow("身份不一致");
  });

  it("keeps bars-only partial output free of technical values", () => {
    const viewModel = buildIndexMinuteBarsOnlyViewModel(makeBarsResponse(makeBars(3)));

    expect(viewModel.indicatorSource).toBe("unavailable");
    expect(viewModel.paramsKey).toBeNull();
    expect(viewModel.indicatorVersion).toBeNull();
    expect(viewModel.points.every((point) => point.ma5 === null && point.macd === null)).toBe(true);
  });
});

function makeBars(count: number): IndexMinuteBarDto[] {
  return Array.from({ length: count }, (_, index) => {
    const minute = 30 + index;
    const tradeTime = `2026-07-01T${String(9 + Math.floor(minute / 60)).padStart(2, "0")}:${String(minute % 60).padStart(2, "0")}:00+08:00`;
    return {
      tsCode: "000001.SH",
      freq: 1,
      tradeDate: "2026-07-01",
      tradeTime,
      open: 100 + index,
      high: 102 + index,
      low: 99 + index,
      close: 101 + index,
      vol: 10_000 + index,
      amount: 1_000_000 + index,
      exchange: "SSE",
    };
  });
}

function makeIndicators(bars: IndexMinuteBarDto[]): IndexMinuteIndicatorDto[] {
  return bars.map((bar, index) => ({
    tsCode: bar.tsCode,
    freq: bar.freq,
    tradeDate: bar.tradeDate,
    tradeTime: bar.tradeTime,
    ma5: index < 4 ? null : 100 + index,
    ma10: null,
    ma20: null,
    ma30: null,
    ma60: null,
    ma90: null,
    ma250: null,
    bollMiddle: index < 19 ? null : 100 + index,
    bollUpper: index < 19 ? null : 102 + index,
    bollLower: index < 19 ? null : 98 + index,
    macdDif: index / 10,
    macdDea: index / 20,
    macd: index / 10,
    kdjK: index < 8 ? null : 50 + index,
    kdjD: index < 8 ? null : 45 + index,
    kdjJ: index < 8 ? null : 60 + index,
    observationCount: index + 1,
    paramsKey: PARAMS_KEY,
    indicatorVersion: 1,
  }));
}

function makeBarsResponse(bars: IndexMinuteBarDto[]): IndexMinutesResponseDto {
  return {
    tsCode: "000001.SH",
    freq: 1,
    bars,
    meta: { count: bars.length, limit: 500, hasMore: false, nextCursor: null, startDate: null, endDate: "2026-07-31", observedStartDate: "2026-07-01", observedEndDate: "2026-07-01" },
    dataStatus: { status: "READY", code: null, expectedEndDate: "2026-07-31", observedEndDate: "2026-07-31", message: null },
  };
}

function makeIndicatorsResponse(items: IndexMinuteIndicatorDto[]): IndexMinuteIndicatorsResponseDto {
  return {
    tsCode: "000001.SH",
    freq: 1,
    items,
    meta: { count: items.length, limit: 500, hasMore: false, nextCursor: null, startDate: null, endDate: "2026-07-31", observedStartDate: "2026-07-01", observedEndDate: "2026-07-01" },
    dataStatus: { status: "READY", code: null, expectedEndDate: "2026-07-31", observedEndDate: "2026-07-31", message: null },
  };
}
