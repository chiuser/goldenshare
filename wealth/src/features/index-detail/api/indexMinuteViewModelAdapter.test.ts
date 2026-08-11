import { describe, expect, it } from "vitest";

import type { IndexMinuteBarDto, IndexMinutesResponseDto } from "./indexDetailApiTypes";
import {
  buildIndexMinuteMockIndicators,
  INDEX_MINUTE_MOCK_INDICATOR_VERSION,
  INDEX_MINUTE_MOCK_PARAMS_KEY,
} from "./indexMinuteMockIndicatorProvider";
import { buildIndexMinuteBarsOnlyViewModel, buildIndexMinuteChartViewModel } from "./indexMinuteViewModelAdapter";

describe("index minute mock indicators", () => {
  it("uses deterministic frozen parameters and preserves warm-up nulls", () => {
    const bars = makeBars(250);
    const indicators = buildIndexMinuteMockIndicators(bars);

    expect(indicators[3]!.ma5).toBeNull();
    expect(indicators[4]!.ma5).not.toBeNull();
    expect(indicators[18]!.bollMiddle).toBeNull();
    expect(indicators[19]!.bollMiddle).not.toBeNull();
    expect(indicators[7]!.kdjK).toBeNull();
    expect(indicators[8]!.kdjK).not.toBeNull();
    expect(indicators[248]!.ma250).toBeNull();
    expect(indicators[249]!.ma250).not.toBeNull();
    expect(indicators[249]!.observationCount).toBe(250);
  });

  it("sorts descending API bars for the chart and identifies the data as mock v0", () => {
    const response = makeResponse([...makeBars(20)].reverse());
    const viewModel = buildIndexMinuteChartViewModel(response);

    expect(viewModel.points[0]!.time).toBeLessThan(viewModel.points.at(-1)!.time);
    expect(viewModel.indicatorSource).toBe("mock");
    expect(viewModel.paramsKey).toBe(INDEX_MINUTE_MOCK_PARAMS_KEY);
    expect(viewModel.indicatorVersion).toBe(INDEX_MINUTE_MOCK_INDICATOR_VERSION);
    expect(viewModel.points[0]!.preClose).toBeNull();
    expect(viewModel.points[0]!.changePct).toBeNull();
  });

  it("does not label bars-only partial output as mock indicators", () => {
    const viewModel = buildIndexMinuteBarsOnlyViewModel(makeResponse(makeBars(3)));

    expect(viewModel.indicatorSource).toBe("unavailable");
    expect(viewModel.paramsKey).toBeNull();
    expect(viewModel.indicatorVersion).toBeNull();
    expect(viewModel.points.every((point) => point.ma5 === null && point.macd === null)).toBe(true);
  });
});

function makeBars(count: number): IndexMinuteBarDto[] {
  return Array.from({ length: count }, (_, index) => {
    const timestamp = new Date(Date.UTC(2026, 6, 1, 1, 30 + index));
    const tradeTime = timestamp.toISOString().replace("Z", "+08:00");
    return {
      tsCode: "000001.SH",
      freq: 1,
      tradeDate: tradeTime.slice(0, 10),
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

function makeResponse(bars: IndexMinuteBarDto[]): IndexMinutesResponseDto {
  return {
    tsCode: "000001.SH",
    freq: 1,
    bars,
    meta: { count: bars.length, limit: 500, hasMore: false, nextCursor: null, startDate: null, endDate: "2026-07-31", observedStartDate: "2026-07-01", observedEndDate: "2026-07-01" },
    dataStatus: { status: "READY", code: null, expectedEndDate: "2026-07-31", observedEndDate: "2026-07-31", message: null },
  };
}
