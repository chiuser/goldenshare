import { describe, expect, it } from "vitest";

import { buildSectorRelativeRotationSearch, DEFAULT_RELATIVE_ROTATION_URL_STATE, parseSectorRelativeRotationUrlState } from "./sectorRelativeRotationUrlState";

describe("sectorRelativeRotationUrlState", () => {
  it("uses the eleven-key frozen defaults and canonical omission", () => {
    expect(parseSectorRelativeRotationUrlState("")).toEqual({ ok: true, value: DEFAULT_RELATIVE_ROTATION_URL_STATE });
    expect(buildSectorRelativeRotationSearch(DEFAULT_RELATIVE_ROTATION_URL_STATE)).toBe("");
  });

  it("round-trips every recoverable state", () => {
    const search = "?market=CN_A&debug=1&tradeDate=2026-08-27&scope=level2-children&level1Code=BK1001.DC&level2Code=BK1101.DC&period=30&trailLength=60&sectorCode=BK1201.DC&quadrant=weak-improving&search=%E9%80%9A%E4%BF%A1";
    const parsed = parseSectorRelativeRotationUrlState(search);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parseSectorRelativeRotationUrlState(buildSectorRelativeRotationSearch(parsed.value))).toEqual(parsed);
  });

  it.each([
    ["?unknown=1", "不支持的页面参数"],
    ["?period=5&period=10", "不能重复"],
    ["?tradeDate=2026-02-30", "真实的"],
    ["?scope=level1&level1Code=BK1001.DC", "不能携带父级"],
    ["?scope=level1-children", "必须且只能"],
    ["?scope=level1-children&level1Code=BK1001.DC&level2Code=BK1101.DC", "必须且只能"],
    ["?scope=level2-children&level1Code=BK1001.DC", "必须同时"],
    [`?search=${"行".repeat(65)}`, "64"],
    ["?sectorCode=bad", "BKxxxx.DC"],
  ])("fails closed for %s", (search, message) => {
    const parsed = parseSectorRelativeRotationUrlState(search);
    expect(parsed.ok).toBe(false);
    if (!parsed.ok) expect(parsed.message).toContain(message);
  });

  it("trims search and omits an empty value", () => {
    const parsed = parseSectorRelativeRotationUrlState("?search=%20%E9%80%9A%E4%BF%A1%20");
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value.search).toBe("通信");
    expect(buildSectorRelativeRotationSearch({ ...parsed.value, search: "" })).toBe("");
  });
});
