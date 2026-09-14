import { describe, expect, it } from "vitest";
import { parseContract } from "./contractValidation";
import { validRecordCombination } from "./recordContractSemantics";

const id = "00000000-0000-0000-0000-000000000001";
const trade = { accountRef: { accountId: id, name: "账户", brokerName: "券商" },
  stockRef: { tsCode: "600036.SH", name: "招商银行" }, tradeId: id, revision: "1",
  tradeDate: "2026-09-07", recordedAt: "2026-09-07T16:00:00+08:00", acceptedAt: "2026-09-07T16:00:00+08:00",
  direction: "SELL", quantity: 1, price: "10.00", grossAmount: "10.00", commissionAmount: "0.00",
  stampTaxAmount: "0.00", netCashChange: "10.00", feeVersionId: id, commissionRateWan: "0.00",
  minimumCommission: "0.00", stampTaxRatePct: "0.00", note: null, status: "ACTIVE",
  closedDataStatus: "Ready", closedReason: null };

describe("raw trade closed-result contract", () => {
  it("cannot advertise a ready detail without published evidence or with a different source revision", () => {
    const detail = { record: trade, closedDataStatus: "Ready", reason: null, closedTrade: null };
    expect(validRecordCombination("TradeDetail", detail)).toBe(false);
    const closed = { tradeId: trade.tradeId, sellRevision: "2", accountRef: trade.accountRef, stockRef: trade.stockRef };
    expect(validRecordCombination("TradeDetail", { ...detail, closedTrade: closed })).toBe(false);
    expect(validRecordCombination("TradeDetail", { ...detail, closedTrade: { ...closed, sellRevision: "1" } })).toBe(true);
    expect(validRecordCombination("TradeDetail", { ...detail, closedDataStatus: "Delayed", reason: "待行情" })).toBe(false);
  });
  it("keeps raw facts while waiting and accepts published status", () => {
    expect(parseContract("TradeRecord", trade)).toBe(trade);
    expect(() => parseContract("TradeRecord", { ...trade, closedDataStatus: "Recalculating", closedReason: "待计算" })).not.toThrow();
  });
  it.each([{ closedDataStatus: undefined }, { closedReason: undefined }, { closedDataStatus: "Delayed" },
    { closedReason: "旧原因" }, { status: "VOID" }, { direction: "BUY", netCashChange: "-10.00" },
    { closedDataStatus: "Error", closedReason: " " }])("rejects invalid closed state %j", patch => {
    expect(() => parseContract("TradeRecord", { ...trade, ...patch })).toThrow();
  });
});
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
