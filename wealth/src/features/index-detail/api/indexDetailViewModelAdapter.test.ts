import { describe, expect, it } from "vitest";

import { formatIndexVolumeLots } from "../model/formatIndexVolumeLots";
import { makeKline, makePageInit } from "../testing/indexDetailTestFixtures";
import { buildIndexDailyTrendChannelPoints, buildIndexDetailViewModel } from "./indexDetailViewModelAdapter";

describe("buildIndexDetailViewModel", () => {
  it("keeps the frozen 15-field order and renders missing values as dash", () => {
    const pageInit = makePageInit();
    pageInit.dailyBasic = { tradeDate: "2026-07-31", pe: null, peTtm: 13.2, pb: null, turnoverRate: 1.14, floatMv: null, totalMv: 6_951_000_000_000 };
    const viewModel = buildIndexDetailViewModel(pageInit, makeKline());

    expect(viewModel.basicMetrics.map((item) => item.label)).toEqual([
      "昨收", "今开", "总量", "最高", "最低", "金额", "市盈率", "TTM 市盈率", "市净率", "换手率", "流通市值", "总市值", "上涨数", "平盘数", "下跌数",
    ]);
    expect(viewModel.basicMetrics.find((item) => item.key === "pe")?.value).toBe("--");
    expect(viewModel.basicMetrics.find((item) => item.key === "pb")?.value).toBe("--");
    expect(viewModel.basicMetrics.find((item) => item.key === "totalMv")?.value).toBe("6.95万亿");
    expect(viewModel.basicMetrics.find((item) => item.key === "vol")?.value).toBe("5.42亿手");
    expect(viewModel.chart.candles[0]).toMatchObject({ volume: 500_000_000, volumeDisplay: "5亿手", amount: 110_000_000 });
    expect(viewModel.periods.filter((period) => period.supported).map((period) => period.key)).toEqual(["day"]);
  });

  it("does not synthesize missing factor values as zero", () => {
    const kline = makeKline();
    kline.bars[0].factors.ma.ma250 = null;
    const viewModel = buildIndexDetailViewModel(makePageInit(), kline);
    expect(viewModel.chart.candles[0].ma250).toBeNull();
  });

  it("requires both page-init capability fields before enabling a long period", () => {
    const pageInit = makePageInit();
    const supported = () => buildIndexDetailViewModel(pageInit, makeKline())
      .periods.filter(period => period.supported).map(period => period.key);
    pageInit.chartDefaults.availablePeriods.push("week");
    expect(supported()).toEqual(["day"]);
    pageInit.capabilities.supportsWeeklyMonthly = true;
    expect(supported()).toEqual(["day", "week"]);
    pageInit.chartDefaults.availablePeriods.push("month");
    expect(supported()).toEqual(["day", "week", "month"]);
  });
});

describe("index volume display in lots", () => {
  it("formats fractional lots, ten-thousands, and hundreds of millions of lots", () => {
    expect([null, 0, 123.45, 10_000, 2_426_761.31, 100_000_000].map(formatIndexVolumeLots))
      .toEqual(["--", "0手", "123.45手", "1万手", "242.68万手", "1亿手"]);
  });
});

describe("same-page SSE four rails", () => {
  it("maps different literal rails in date order and allows common warmup nulls", () => {
    expect(buildIndexDailyTrendChannelPoints(makeKline())).toEqual([
      { time: "2026-07-30", close: 3930, shortUpper: 3951, shortLower: 3881, longUpper: 3971, longLower: 3861 },
      { time: "2026-07-31", close: 3940, shortUpper: 3952, shortLower: 3882, longUpper: 3972, longLower: 3862 },
    ]);
    expect(buildIndexDailyTrendChannelPoints(makeKline("399001.SZ"))).toEqual([]);
    expect(buildIndexDailyTrendChannelPoints({ ...makeKline(), bars: [] })).toEqual([]);
  });

  it.each(["missing", "null", "nan", "date", "order"])("rejects a %s rail page instead of dropping individual bars", fault => {
    const data = structuredClone(makeKline());
    const bar = data.bars[1]!;
    if (fault === "date") bar.tradeDate = "bad-date";
    else if (fault === "order") bar.tradeDate = data.bars[0]!.tradeDate;
    else Object.assign(bar.factors, { trendChannel: fault === "missing" ? undefined : {
      shortUpper: fault === "nan" ? NaN : null, shortLower: 1, longUpper: 3, longLower: 2,
    } });
    expect(() => buildIndexDailyTrendChannelPoints(data)).toThrow("趋势通道");
  });
});
