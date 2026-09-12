import { describe, expect, it } from "vitest";
import { parseContract } from "./contractValidation";

const accountId = "00000000-0000-0000-0000-000000000001";
const fees = { accountId, feeVersionId: "00000000-0000-0000-0000-000000000002", commissionRateWan: "2.50", minimumCommission: "5.00", stampTaxRatePct: "0.05" };
const entry = { accountId, factVersion: "1", occurredOn: "2026-09-11", cashThrough: "2026-09-11T15:00:00+08:00",
  availableCash: "0.00", stockRef: { tsCode: "000001.SZ", name: "测试股票" }, quantity: "9007199254740992", availableQuantity: "9007199254740991",
  fees, calendarDataStatus: "Ready", reason: null };

describe("generated TA contract runtime", () => {
  it("retains exact strings, zero, null and required keys without reshaping", () => {
    expect(parseContract("EntryContext", entry)).toBe(entry);
  });
  it.each([
    { availableCash: 0 }, { availableCash: "-0.00" }, { availableCash: "-1.00" }, { availableCash: "1.00\n" },
    { quantity: 9007199254740992 }, { availableQuantity: "9007199254740993" },
    { factVersion: "9223372036854775808" }, { occurredOn: "2026-02-30" },
    { fees: { ...fees, stampTaxRatePct: "100.01" } },
    { fees: { ...fees, accountId: fees.feeVersionId } }, { reason: undefined }, { extra: "forbidden" },
  ])("rejects malformed or contradictory response %j", (patch) => {
    expect(() => parseContract("EntryContext", { ...entry, ...patch })).toThrow();
  });
  it("requires nullable fields even when no data is available", () => {
    const { reason: _reason, ...missing } = entry;
    expect(() => parseContract("EntryContext", missing)).toThrow();
    expect(() => parseContract("EntryContext", { ...entry, stockRef: null, quantity: null, availableQuantity: null })).not.toThrow();
  });
  it("rejects unsafe JSON share integers and allows odd lots", () => {
    const row = { clientRowId: "row-1", tsCode: "000001.SZ", quantity: 13, availableQuantity: 3, costPrice: "10.00" };
    expect(parseContract("InitializationPositionInput", row)).toBe(row);
    expect(() => parseContract("InitializationPositionInput", { ...row, quantity: 9007199254740992 })).toThrow();
    expect(() => parseContract("InitializationPositionInput", { ...row, availableQuantity: 14 })).toThrow();
  });
});
