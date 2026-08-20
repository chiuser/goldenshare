import { describe, expect, it } from "vitest";

import { makeKline, makePageInit } from "../testing/indexDetailTestFixtures";
import { buildIndexDetailViewModel } from "./indexDetailViewModelAdapter";

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
    expect(viewModel.basicMetrics.find((item) => item.key === "vol")?.value).toBe("5.42万");
    expect(viewModel.chart.candles[0].volumeDisplay).toBe("5.00万");
    expect(viewModel.periods.filter((period) => period.supported).map((period) => period.key)).toEqual(["day"]);
  });

  it("does not synthesize missing factor values as zero", () => {
    const kline = makeKline();
    kline.bars[0].factors.ma.ma250 = null;
    const viewModel = buildIndexDetailViewModel(makePageInit(), kline);
    expect(viewModel.chart.candles[0].ma250).toBeNull();
  });
});
