import { describe, expect, it } from "vitest";

import {
  buildMajorIndicesViewModelFromApi,
  buildTopMarketTickersFromMajorIndices,
} from "./marketMajorIndicesAdapter";

describe("marketMajorIndicesAdapter", () => {
  it("shares one real response mapping with the top market bar", () => {
    const model = buildMajorIndicesViewModelFromApi({
      tradingDay: {
        tradeDate: "2026-08-21",
        market: "CN_A",
        isTradingDay: true,
        sessionStatus: "CLOSED",
        timezone: "Asia/Shanghai",
      },
      pageStatus: { status: "READY", displayText: "已就绪" },
      majorIndices: {
        definition: { definitionKey: "major", version: "1", fixedCount: 10 },
        rows: [
          {
            subject: { subjectType: "index", subjectCode: "000001.SH", subjectName: "上证指数" },
            point: 3825.76,
            change: 12.3,
            changePct: 0.45,
            amount: 100,
            direction: "UP",
          },
          {
            subject: { subjectType: "index", subjectCode: "399001.SZ", subjectName: "深证成指" },
            point: null,
            change: null,
            changePct: null,
            amount: null,
            direction: "FLAT",
          },
        ],
      },
    });

    expect(model.source).toBe("real");
    expect(buildTopMarketTickersFromMajorIndices(model)).toEqual([
      {
        code: "000001.SH",
        name: "上证指数",
        point: 3825.76,
        change: 12.3,
        pct: 0.45,
        direction: "UP",
      },
    ]);
  });
});
