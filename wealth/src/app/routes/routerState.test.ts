import { describe, expect, it } from "vitest";

import { buildIndexDetailPath, buildStockDetailPath } from "./routerState";

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
