import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_WEALTH_PATH,
  buildIndexDetailPath,
  buildStockDetailPath,
  navigateWealth,
  returnToWealthOverview,
} from "./routerState";

afterEach(() => {
  vi.restoreAllMocks();
  window.history.replaceState({}, "", DEFAULT_WEALTH_PATH);
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
