import { describe, expect, it } from "vitest";
import { parseContract } from "./contractValidation";

const id = "00000000-0000-0000-0000-000000000001";
const group = { accountRef: { accountId: id, name: "账户", brokerName: "券商" }, tradeDate: "2026-09-07",
  stockRef: { tsCode: "600036.SH", name: "招商银行" }, direction: "SELL", quantity: "5000",
  grossAmount: "201600.00", averagePrice: "40.32", commissionAmount: "50.40", stampTaxAmount: "100.80",
  netCashChange: "201448.80", tradeCount: 2,
  recordsScope: { accountId: id, tsCode: "600036.SH", tradeDate: "2026-09-07", direction: "SELL" },
  allocatedCost: "200050.00", closedProfitAmount: "1398.80", closedReturnPct: "0.70", closedDataStatus: "Ready", reason: null };

describe("daily closed-result contract", () => {
  it("accepts the formal design example and unknown derived data without losing raw facts", () => {
    expect(parseContract("TradeDayGroup", group)).toBe(group);
    expect(() => parseContract("TradeDayGroup", { ...group, allocatedCost: null, closedProfitAmount: null,
      closedReturnPct: null, closedDataStatus: "Recalculating", reason: "待计算" })).not.toThrow();
    expect(() => parseContract("TradeDayGroup", { ...group, allocatedCost: "201448.80", closedProfitAmount: "0.00", closedReturnPct: "0.00" })).not.toThrow();
  });
  it.each([{ allocatedCost: undefined }, { allocatedCost: null }, { allocatedCost: "0.00" },
    { closedProfitAmount: "1398.79" }, { closedDataStatus: "Recalculating" }, { closedDataStatus: "Empty" },
    { tradeCount: 0 }, { reason: "旧状态" }, { netCashChange: "201600.00" }, { extra: 1 },
    { recordsScope: { ...group.recordsScope, direction: "BUY" } },
  ])("rejects inconsistent group %j", patch => {
    expect(() => parseContract("TradeDayGroup", { ...group, ...patch })).toThrow();
  });
});
