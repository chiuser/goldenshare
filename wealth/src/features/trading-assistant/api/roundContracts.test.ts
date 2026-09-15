import { describe, expect, it } from "vitest";
import { parseContract } from "./contractValidation";

const id = "00000000-0000-0000-0000-000000000001";
const other = "00000000-0000-0000-0000-000000000002";
const account = { accountId: id, name: "账户", brokerName: "券商" };
const cover = { accountId: id, initializedOn: "2026-09-01", effectiveStartDate: "2026-09-01",
  targetThroughDate: "2026-09-11", calculatedThroughDate: "2026-09-11",
  valuationAt: "2026-09-11T16:00:00+08:00", dataStatus: "Ready", reason: null };
const detail = { accountRef: account, stockRef: { tsCode: "000001.SZ", name: "平安银行" },
  roundRef: { accountId: id, roundId: other, roundNumber: 1, status: "CLOSED" },
  openedOn: "2026-09-01", closedOn: "2026-09-11", openingSource: "TRADE", initializationSource: null,
  buyQuantity: "1000", sellQuantity: "1000", buyInvestmentAmount: "10000.00", sellNetProceedsAmount: "11000.00",
  roundProfitAmount: "1000.00", roundReturnPct: "10.00", closedTradeCount: 1,
  recordsScope: { accountId: id, roundId: other } };
const ready = { readContext: { contextToken: "test", targetThrough: "2026-09-11T16:00:00+08:00",
  accounts: [{ accountId: id, factVersion: "1", calculationTargetVersion: "1", publishedGenerationId: other }] },
  coverage: { dataStatus: "Ready", reason: null, isFinal: true, accounts: [cover] }, detail };

describe("round detail state envelope", () => {
  it("accepts complete Ready detail", () => {
    expect(parseContract("RoundDetailResponse", ready)).toBe(ready);
  });
  it.each(["Delayed", "Recalculating", "Error", "Partial"])("%s carries status, never old detail", state => {
    const pending = { ...ready, detail: null, coverage: { ...ready.coverage,
      dataStatus: state, reason: "正在重新计算", isFinal: false,
      accounts: [{ ...cover, dataStatus: state, reason: "正在重新计算" }] } };
    expect(parseContract("RoundDetailResponse", pending)).toBe(pending);
    expect(() => parseContract("RoundDetailResponse", { ...pending, detail })).toThrow();
    expect(() => parseContract("RoundDetailResponse", { ...pending,
      coverage: { ...pending.coverage, reason: " " } })).toThrow();
  });
  it("rejects missing keys, stale shape, mismatched account or round, and Ready without data", () => {
    for (const bad of [detail, { ...ready, detail: null }, { ...ready, extra: true },
      { ...ready, readContext: undefined }, { ...ready, coverage: undefined }, { ...ready, detail: undefined },
      { ...ready, coverage: { ...ready.coverage, accounts: [] } },
      { ...ready, detail: { ...detail, accountRef: { ...account, accountId: other } } },
      { ...ready, detail: { ...detail, recordsScope: { accountId: id, roundId: id } } }]) {
      expect(() => parseContract("RoundDetailResponse", bad)).toThrow();
    }
  });
});
