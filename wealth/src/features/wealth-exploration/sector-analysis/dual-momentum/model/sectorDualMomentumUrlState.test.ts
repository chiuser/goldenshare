import { describe, expect, it } from "vitest";

import {
  buildSectorDualMomentumSearch,
  DEFAULT_DUAL_MOMENTUM_URL_STATE,
  parseSectorDualMomentumUrlState,
} from "./sectorDualMomentumUrlState";

describe("sectorDualMomentumUrlState", () => {
  it("uses the frozen default state", () => {
    expect(parseSectorDualMomentumUrlState("")).toEqual({ ok: true, value: DEFAULT_DUAL_MOMENTUM_URL_STATE });
  });

  it("parses and rebuilds all ten URL keys", () => {
    const search = "?market=CN_A&debug=1&tradeDate=2026-08-27&scope=level2-children"
      + "&level1Code=BK1001.DC&level2Code=BK1101.DC&period=30&threshold=90"
      + "&resultView=all&sectorCode=BK1201.DC";
    const parsed = parseSectorDualMomentumUrlState(search);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parsed.value).toMatchObject({
      debug: true, tradeDate: "2026-08-27", scope: "level2-children",
      level1Code: "BK1001.DC", level2Code: "BK1101.DC", period: 30,
      threshold: 90, resultView: "all", sectorCode: "BK1201.DC",
    });
    expect(parseSectorDualMomentumUrlState(buildSectorDualMomentumSearch(parsed.value))).toEqual(parsed);
  });

  it.each(["level1", "level2", "level3", "level1-children", "level2-children"])("accepts scope %s", (scope) => {
    expect(parseSectorDualMomentumUrlState(`?scope=${scope}`).ok).toBe(true);
  });

  it.each([5, 10, 20, 30])("accepts period %s", (period) => {
    expect(parseSectorDualMomentumUrlState(`?period=${period}`).ok).toBe(true);
  });

  it.each([70, 80, 90])("accepts threshold %s", (threshold) => {
    expect(parseSectorDualMomentumUrlState(`?threshold=${threshold}`).ok).toBe(true);
  });

  it.each([
    "?extra=1",
    "?period=20&period=30",
    "?market=US",
    "?debug=true",
    "?tradeDate=2026-02-30",
    "?scope=all",
    "?period=1",
    "?threshold=85",
    "?resultView=top",
    "?sectorCode=INVALID",
  ])("rejects illegal URL %s", (search) => {
    expect(parseSectorDualMomentumUrlState(search).ok).toBe(false);
  });

  it("omits frozen defaults while preserving legal hidden parents", () => {
    expect(buildSectorDualMomentumSearch({
      ...DEFAULT_DUAL_MOMENTUM_URL_STATE,
      level1Code: "BK1001.DC",
      level2Code: "BK1101.DC",
    })).toBe("?level1Code=BK1001.DC&level2Code=BK1101.DC");
  });
});
