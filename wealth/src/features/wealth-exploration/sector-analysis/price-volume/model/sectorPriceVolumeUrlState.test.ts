import { describe, expect, it } from "vitest";

import { buildSectorPriceVolumeSearch, parseSectorPriceVolumeUrlState } from "./sectorPriceVolumeUrlState";

describe("sectorPriceVolumeUrlState", () => {
  it("uses the frozen defaults and restores every supported state field", () => {
    expect(parseSectorPriceVolumeUrlState("")).toEqual({
      ok: true,
      value: { tradeDate: null, scope: "level1", level1Code: null, level2Code: null, period: 20, stateFilter: "all", sortBy: "price-momentum", sortDirection: "desc", sectorCode: null, historyRange: 20 },
    });
    const search = "?tradeDate=2026-08-27&scope=level2-children&level1Code=BK1001.DC&level2Code=BK1101.DC&period=30&stateFilter=joint&sortBy=amount-activity&sortDirection=asc&sectorCode=BK1201.DC&historyRange=60";
    const parsed = parseSectorPriceVolumeUrlState(search);
    expect(parsed.ok).toBe(true);
    if (parsed.ok) expect(buildSectorPriceVolumeSearch(parsed.value)).toBe(search);
  });

  it.each([
    ["?debug=1", "不支持的页面参数"],
    ["?period=10&period=20", "不能重复"],
    ["?tradeDate=2026-02-30", "交易日"],
    ["?scope=level1&level1Code=BK1001.DC", "总榜不能携带"],
    ["?scope=level1-children", "必须且只能选择一级"],
    ["?scope=level2-children&level1Code=BK1001.DC", "必须同时选择"],
    ["?stateFilter=hot", "状态筛选"],
    ["?sortBy=rank", "排序字段"],
    ["?historyRange=10", "历史范围"],
  ])("rejects illegal URL %s", (search, message) => {
    expect(parseSectorPriceVolumeUrlState(search)).toEqual({ ok: false, message: expect.stringContaining(message) });
  });
});
