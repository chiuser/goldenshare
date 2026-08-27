import { describe, expect, it } from "vitest";

import {
  buildSectorMomentumSearch,
  parseSectorMomentumUrlState,
} from "./sectorMomentumUrlState";

describe("sectorMomentumUrlState", () => {
  it("uses the frozen defaults without forcing them into the URL", () => {
    const parsed = parseSectorMomentumUrlState("");
    expect(parsed).toEqual({
      ok: true,
      value: {
        market: "CN_A",
        debug: false,
        tradeDate: null,
        scope: "level1",
        level1Code: null,
        level2Code: null,
        period: 1,
        direction: "gainers",
        range: 20,
        sectorCode: null,
      },
    });
    if (parsed.ok) expect(buildSectorMomentumSearch(parsed.value)).toBe("");
  });

  it("round-trips every restorable workspace selection", () => {
    const search = "?debug=1&tradeDate=2026-08-21&scope=level2-children&level1Code=BK1001.DC&level2Code=BK1101.DC&period=30&direction=losers&range=60&sectorCode=BK1201.DC";
    const parsed = parseSectorMomentumUrlState(search);
    expect(parsed.ok).toBe(true);
    if (!parsed.ok) return;
    expect(parseSectorMomentumUrlState(buildSectorMomentumSearch(parsed.value))).toEqual(parsed);
  });

  it.each([
    ["unknown key", "?period=5&extra=1"],
    ["duplicate key", "?period=5&period=10"],
    ["unsupported market", "?market=HK"],
    ["invalid date", "?tradeDate=2026-02-30"],
    ["invalid scope", "?scope=all"],
    ["invalid period", "?period=15"],
    ["invalid direction", "?direction=hot"],
    ["invalid range", "?range=250"],
    ["invalid code", "?sectorCode=BK1.DC"],
  ])("rejects %s before a sector request", (_label, search) => {
    expect(parseSectorMomentumUrlState(search).ok).toBe(false);
  });
});
