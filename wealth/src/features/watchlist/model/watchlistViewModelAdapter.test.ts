import { describe, expect, it } from "vitest";
import { item } from "../test/watchlistFixtures";
import { buildWatchlistRow } from "./watchlistViewModelAdapter";

describe("watchlist display units", () => {
  it.each([
    [2189.4, "+2189.40"],
    [-2189.4, "-2189.40"],
    [1000, "+1000.00"],
    [0.01, "+0.01"],
    [12345678.9, "+12345678.90"],
    [0, "0.00"],
    [null, "--"],
  ] as const)(
    "preserves %s ten-thousand yuan without rescaling",
    (netAmount, expected) => {
      const row = buildWatchlistRow(
        item(1, { moneyFlow: { netAmount, direction: "UNKNOWN" } }),
      );
      expect(row.netAmount).toBe(expected);
      expect(row.vol).toBe("123.46");
    },
  );

  it.each([
    [5.62, 0.71, "5.62", "0.71"],
    [null, 0.71, "--", "0.71"],
    [5.62, null, "5.62", "--"],
    [0, -1, "--", "--"],
  ] as const)(
    "keeps PE %s and PB %s independently formatted",
    (peTtm, pb, peText, pbText) => {
      const row = buildWatchlistRow(item(1, { valuation: { peTtm, pb } }));
      expect(row.peTtm).toBe(peText);
      expect(row.pb).toBe(pbText);
    },
  );
});
