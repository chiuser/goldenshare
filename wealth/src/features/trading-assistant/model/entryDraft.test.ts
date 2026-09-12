import { describe, expect, it } from "vitest";
import { beijingInputDate, formatBeijingInstant, validateEntryDraft, type EntryDraft } from "./entryDraft";
const draft: EntryDraft = { kind: "TRADE", direction: "BUY", stock: { tsCode: "000001.SZ", name: "测试" },
  date: "2026-09-11", price: "10.00", quantity: "13", amount: "", note: "" };
describe("entry input", () => {
  it("accepts odd lots without converting decimal money to a number", () => {
    expect(validateEntryDraft(draft)).toEqual({ errors: [], input: { tsCode: "000001.SZ", direction: "BUY", tradeDate: "2026-09-11", price: "10.00", quantity: 13, note: "" } });
  });
  it.each(["", "0", "1.5", "1e3", "9007199254740992"])("rejects invalid single quantity %s", quantity => {
    expect(validateEntryDraft({ ...draft, quantity }).input).toBeNull();
  });
  it("rejects empty/zero cash, nonexistent dates and mismatched directions", () => {
    for (const amount of ["", "0.00", "NaN"]) expect(validateEntryDraft({ ...draft, kind: "CASH", direction: "OUT", amount }).input).toBeNull();
    expect(validateEntryDraft({ ...draft, date: "2026-02-30" }).input).toBeNull();
    expect(validateEntryDraft({ ...draft, kind: "CASH", amount: "1.00" }).input).toBeNull();
  });
  it("uses Beijing date for the editable default, not UTC", () => {
    expect(beijingInputDate(new Date("2026-09-11T16:01:00Z"))).toBe("2026-09-12");
    expect(formatBeijingInstant("2026-09-11T08:00:00Z")).toBe("2026-09-11 16:00");
  });
});
