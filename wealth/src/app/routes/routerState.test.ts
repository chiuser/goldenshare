import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_WEALTH_PATH,
  buildLoginPath,
  isLoginPath,
  readRedirectPath,
  WEALTH_EXPLORATION_PATH,
  WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH,
  WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH,
  WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH,
  WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH,
  WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH,
  WEALTH_EXPLORATION_SECTOR_PATH,
  WEALTH_EXPLORATION_TURNOVER_PATH,
  buildIndexDetailPath,
  buildSectorAnalysisDualMomentumPath,
  buildSectorAnalysisMomentumPath,
  buildSectorAnalysisMemberBreadthPath,
  buildSectorAnalysisPriceVolumePath,
  buildSectorAnalysisRelativeRotationPath,
  buildSectorAnalysisPath,
  buildStockDetailPath,
  buildTurnoverInsightPath,
  buildWealthExplorationPath,
  navigateWealth,
  resolveWealthExplorationRoute,
  resolveTopMarketNavPath,
  returnToWealthOverview,
} from "./routerState";

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, "", DEFAULT_WEALTH_PATH);
});

describe("login redirect contract U06", () => {
  it.each(["", "?redirect=relative", "?redirect=%2F%2Fexample.com"])("uses default for %s", (query) => {
    expect(readRedirectPath(query)).toBe(DEFAULT_WEALTH_PATH);
  });
  it("preserves a single-slash path and query without adding a new whitelist", () => {
    expect(readRedirectPath("?redirect=%2Fcustom%3Fx%3D1")).toBe("/custom?x=1");
    expect(buildLoginPath("/wealth/market/overview?debug=1")).toBe("/wealth/login?redirect=%2Fwealth%2Fmarket%2Foverview%3Fdebug%3D1");
    expect(isLoginPath("/wealth/login")).toBe(true);
    expect(isLoginPath("/login")).toBe(true);
    expect(isLoginPath("/wealth/login/extra")).toBe(false);
  });
});

describe("buildStockDetailPath", () => {
  it("normalizes stock code case", () => {
    expect(buildStockDetailPath("002245.sz")).toBe("/wealth/market/stock/002245.SZ");
  });

  it("trims surrounding whitespace", () => {
    expect(buildStockDetailPath(" 603806.SH ")).toBe("/wealth/market/stock/603806.SH");
  });

  it("encodes path segment characters", () => {
    expect(buildStockDetailPath("abc/def.sz")).toBe("/wealth/market/stock/ABC%2FDEF.SZ");
  });
});

describe("buildIndexDetailPath", () => {
  it("normalizes, trims and encodes index codes", () => {
    expect(buildIndexDetailPath(" 000001.sh ")).toBe("/wealth/market/index/000001.SH");
    expect(buildIndexDetailPath("abc/def.sz")).toBe("/wealth/market/index/ABC%2FDEF.SZ");
  });
});

describe("wealth exploration route", () => {
  it("builds each exact route while preserving the query", () => {
    const params = new URLSearchParams({ market: "CN_A", tradeDate: "2026-08-21" });
    expect(buildWealthExplorationPath(params)).toBe(
      "/wealth/exploration?market=CN_A&tradeDate=2026-08-21",
    );
    expect(buildTurnoverInsightPath(params)).toBe(
      "/wealth/exploration/turnover-insight?market=CN_A&tradeDate=2026-08-21",
    );
    expect(buildSectorAnalysisPath("?market=CN_A&tradeDate=2026-08-21")).toBe(
      "/wealth/exploration/sector-analysis?market=CN_A&tradeDate=2026-08-21",
    );
    expect(buildSectorAnalysisMomentumPath("?market=CN_A&tradeDate=2026-08-21")).toBe(
      "/wealth/exploration/sector-analysis/momentum-ranking?market=CN_A&tradeDate=2026-08-21",
    );
    expect(buildSectorAnalysisDualMomentumPath("?market=CN_A&tradeDate=2026-08-21")).toBe(
      "/wealth/exploration/sector-analysis/dual-momentum?market=CN_A&tradeDate=2026-08-21",
    );
    expect(buildSectorAnalysisRelativeRotationPath("?market=CN_A&tradeDate=2026-08-21")).toBe(
      "/wealth/exploration/sector-analysis/relative-rotation?market=CN_A&tradeDate=2026-08-21",
    );
    expect(buildSectorAnalysisMemberBreadthPath("?market=CN_A&tradeDate=2026-08-21")).toBe(
      "/wealth/exploration/sector-analysis/member-breadth?market=CN_A&tradeDate=2026-08-21",
    );
    expect(buildSectorAnalysisPriceVolumePath("?market=CN_A&tradeDate=2026-08-21")).toBe(
      "/wealth/exploration/sector-analysis/price-volume?market=CN_A&tradeDate=2026-08-21",
    );
  });

  it("resolves only the eight released exploration paths", () => {
    expect(resolveWealthExplorationRoute(WEALTH_EXPLORATION_PATH)).toEqual({ kind: "landing" });
    expect(resolveWealthExplorationRoute(WEALTH_EXPLORATION_TURNOVER_PATH)).toEqual({ kind: "turnover-insight" });
    expect(resolveWealthExplorationRoute(WEALTH_EXPLORATION_SECTOR_PATH)).toEqual({ kind: "sector-analysis-redirect" });
    expect(resolveWealthExplorationRoute(WEALTH_EXPLORATION_SECTOR_MOMENTUM_PATH)).toEqual({ kind: "sector-analysis-momentum" });
    expect(resolveWealthExplorationRoute(WEALTH_EXPLORATION_SECTOR_DUAL_MOMENTUM_PATH)).toEqual({ kind: "sector-analysis-dual-momentum" });
    expect(resolveWealthExplorationRoute(WEALTH_EXPLORATION_SECTOR_RELATIVE_ROTATION_PATH)).toEqual({ kind: "sector-analysis-relative-rotation" });
    expect(resolveWealthExplorationRoute(WEALTH_EXPLORATION_SECTOR_MEMBER_BREADTH_PATH)).toEqual({ kind: "sector-analysis-member-breadth" });
    expect(resolveWealthExplorationRoute(WEALTH_EXPLORATION_SECTOR_PRICE_VOLUME_PATH)).toEqual({ kind: "sector-analysis-price-volume" });
    expect(resolveWealthExplorationRoute("/wealth/exploration/extra")).toEqual({ kind: "not-exploration" });
    expect(resolveWealthExplorationRoute("/wealth/exploration/sector-analysis/unknown")).toEqual({ kind: "not-exploration" });
  });

  it("maps only released top navigation targets to routes", () => {
    expect(resolveTopMarketNavPath("market")).toBe(DEFAULT_WEALTH_PATH);
    expect(resolveTopMarketNavPath("exploration")).toBe(WEALTH_EXPLORATION_PATH);
    expect(resolveTopMarketNavPath("assistant")).toBeNull();
  });
});

describe("returnToWealthOverview", () => {
  it("uses browser history only for a route entered from within Wealth", () => {
    window.history.replaceState({}, "", DEFAULT_WEALTH_PATH);
    navigateWealth(buildStockDetailPath("603806.SH"));
    const back = vi.spyOn(window.history, "back").mockImplementation(() => undefined);

    returnToWealthOverview();

    expect(back).toHaveBeenCalledOnce();
    expect(window.location.pathname).toBe("/wealth/market/stock/603806.SH");
  });

  it("replaces a direct detail entry with the Wealth overview instead of leaving the site", () => {
    window.history.replaceState({}, "", "/wealth/market/index/000001.SH");
    const back = vi.spyOn(window.history, "back").mockImplementation(() => undefined);

    returnToWealthOverview();

    expect(back).not.toHaveBeenCalled();
    expect(window.location.pathname).toBe(DEFAULT_WEALTH_PATH);
  });
});
