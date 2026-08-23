import { describe, expect, it } from "vitest";

import { adaptStockDetailNews, formatNewsDate } from "./stockDetailNewsViewModelAdapter";

describe("stock detail news view model adapter", () => {
  it("keeps API order and formats dates with the Shanghai year rule", () => {
    const now = new Date("2026-08-23T01:00:00Z");
    const items = adaptStockDetailNews({
      stockRef: { tsCode: "603806.SH", name: "福斯特" },
      items: [
        { newsId: "late", publishTime: "2026-05-29T16:00:03+08:00", title: "后返回" },
        { newsId: "middle", publishTime: "2026-05-29T16:00:02+08:00", title: "中间" },
        { newsId: "old", publishTime: "2025-12-31T23:00:00+08:00", title: "跨年" },
      ],
      meta: { count: 3, limit: 50, startAt: "2026-06-23T00:00:00+08:00", endAt: "2026-08-23T00:00:00+08:00" },
    }, now);

    expect(items.map((item) => item.newsId)).toEqual(["late", "middle", "old"]);
    expect(items.map((item) => item.displayDate)).toEqual(["05-29", "05-29", "2025-12-31"]);
  });

  it("formats the current year in Shanghai rather than browser local time", () => {
    expect(formatNewsDate("2025-12-31T23:30:00Z", new Date("2026-01-01T00:30:00Z"))).toBe("01-01");
  });
});
