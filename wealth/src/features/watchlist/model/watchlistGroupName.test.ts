import { describe, expect, it } from "vitest";
import vectors from "../../../../../tests/fixtures/wealth_watchlist_group_names.json";
import { rules } from "../test/watchlistFixtures";
import { validateWatchlistGroupName } from "./watchlistGroupName";
describe("shared name contract", () => {
  it.each(vectors)("$id", vector => {
    const result = validateWatchlistGroupName(vector.raw, rules, ["我的自选"]);
    expect(!result.error).toBe(vector.accepted);
    if (vector.accepted) expect(result.name).toBe(vector.normalized);
  });
  it("checks byte boundaries independently of grapheme count", () => {
    expect(validateWatchlistGroupName("qq" + "\u0301".repeat(511), rules, []).error).toBe("");
    expect(validateWatchlistGroupName("qqq" + "\u0301".repeat(511), rules, []).error).not.toBe("");
  });
  it("uses NFC and exact trim for conflicts without case folding", () => {
    expect(validateWatchlistGroupName(" e\u0301 ", rules, ["é"]).error).not.toBe("");
    expect(validateWatchlistGroupName("ai", rules, ["AI"]).error).toBe("");
  });
});
