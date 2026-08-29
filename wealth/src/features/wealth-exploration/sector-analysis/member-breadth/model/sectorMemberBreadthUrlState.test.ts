import { describe, expect, it } from "vitest";
import { buildSectorMemberBreadthSearch, parseSectorMemberBreadthUrlState } from "./sectorMemberBreadthUrlState";

describe("sectorMemberBreadthUrlState", () => {
  it("parses and restores the complete frozen URL contract", () => {
    const result = parseSectorMemberBreadthUrlState("?tradeDate=2026-08-27&scope=level2-children&level1Code=BK1001.DC&level2Code=BK1101.DC&direction=down&metric=ma-position&maPeriod=60&historyRange=30&sectorCode=BK1201.DC");
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(buildSectorMemberBreadthSearch(result.value)).toBe("?tradeDate=2026-08-27&scope=level2-children&level1Code=BK1001.DC&level2Code=BK1101.DC&direction=down&metric=ma-position&maPeriod=60&historyRange=30&sectorCode=BK1201.DC");
  });

  it.each([
    ["?debug=1", "不支持的页面参数"], ["?scope=level2-children&level1Code=BK1001.DC", "必须同时选择"], ["?scope=level1&level1Code=BK1001.DC", "总榜不能携带"], ["?maPeriod=25", "均线周期"], ["?historyRange=10", "历史范围"], ["?tradeDate=2026-02-30", "交易日"], ["?metric=member-count&metric=turnover", "不能重复"],
  ])("rejects illegal URL %s", (search, message) => {
    const result = parseSectorMemberBreadthUrlState(search);
    expect(result).toEqual({ ok: false, message: expect.stringContaining(message) });
  });
});
