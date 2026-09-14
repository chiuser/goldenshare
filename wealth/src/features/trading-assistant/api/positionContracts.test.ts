import { describe, expect, it } from "vitest";
import { parseContract } from "./contractValidation";

const row = { stockRef: { tsCode: "600000.SH", name: "股票" }, quantity: "600", availableQuantity: "600",
  dynamicCostPrice: "6.67", dynamicCostAmount: "4000.00", price: "15.00", marketValue: "9000.00",
  holdingProfitAmount: "5000.00", holdingReturnPct: "50.00", dayProfitAmount: "0.00", stockValueWeightPct: "100.00",
  totalAssetWeightPct: "90.00", estimatedSellCommission: "5.00", estimatedStampTax: "4.50", estimatedTotalFeeAmount: "9.50",
  estimatedNetProceeds: "8990.50", industry: null, quoteAt: "2026-09-11T15:00:00+08:00",
  valuationDate: "2026-09-11", priceDate: "2026-09-11", valuationMethod: "SAME_DAY_CLOSE",
  accountRounds: [{ accountId: "00000000-0000-0000-0000-000000000001", roundId: "00000000-0000-0000-0000-000000000002", roundNumber: 1 }],
  dataStatus: "Ready", reason: null };

describe("positions wire invariants", () => {
  it("keeps zero/negative cost, actual source dates and unknown quantities distinct", () => {
    expect(parseContract("PositionRow", row)).toBe(row);
    for (const cost of ["0.00", "-600.00"]) expect(() => parseContract("PositionRow", { ...row, dynamicCostAmount: cost })).not.toThrow();
    expect(() => parseContract("PositionRow", { ...row, valuationMethod: "CONFIRMED_SUSPENSION_CARRY", priceDate: "2026-09-10" })).not.toThrow();
    expect(() => parseContract("PositionRow", { ...row, dataStatus: "Delayed", reason: "等待核算", availableQuantity: null, accountRounds: [] })).not.toThrow();
  });
  it.each([
    { availableQuantity: null }, { availableQuantity: "601" }, { quantity: 600 }, { quantity: "0" },
    { accountRounds: [] }, { accountRounds: [...row.accountRounds, ...row.accountRounds] },
    { estimatedTotalFeeAmount: "9.49" }, { valuationDate: undefined }, { priceDate: null },
    { priceDate: "2026-09-10" }, { valuationMethod: "CONFIRMED_SUSPENSION_CARRY" },
    { marketValue: null }, { marketValue: "Infinity" }, { extra: "forbidden" },
  ])("rejects malformed response %j", patch => {
    expect(() => parseContract("PositionRow", { ...row, ...patch })).toThrow();
  });
  it("rejects incomplete OTHER members and cash in stock-only allocation", () => {
    const member = { stockRef: row.stockRef, marketValue: "100.00", weightPct: "10.00" };
    const slice = { kind: "OTHER", stockRef: null, marketValue: "100.00", weightPct: "10.00", members: [member] };
    expect(parseContract("AllocationSlice", slice)).toBe(slice);
    expect(() => parseContract("AllocationSlice", { ...slice, members: [] })).toThrow();
    expect(() => parseContract("AllocationSlice", { ...slice, marketValue: "200.00" })).toThrow();
    const cash = { kind: "CASH", stockRef: null, marketValue: "100.00", weightPct: "100.00", members: [] };
    expect(() => parseContract("Allocation", { stockMarketValue: "100.00", totalAssets: "100.00", stockValueSlices: [cash], totalAssetSlices: [cash] })).toThrow();
  });
});
