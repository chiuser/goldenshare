import { describe, expect, it } from "vitest";
import { defaultRecordFilter, recordListQuery, recordRange } from "./recordsQuery";
import { parseContract } from "../api/contractValidation";
const id = "00000000-0000-0000-0000-000000000001";
describe("record query scope", () => {
  it("uses a natural month, with an independent all-stock summary", () => {
    const month = defaultRecordFilter("2026-09-15");
    expect(month).toEqual({ start: "2026-09-01", end: "2026-09-15", stock: null, direction: "" });
    expect(recordRange(id, month).stockMode).toBe("ALL");
  });
  it("does not leak stock or trade direction into cash or direction into closed trades", () => {
    const filter = { ...defaultRecordFilter("2026-09-15"), stock: { tsCode: "000001.SZ", name: "平安银行" }, direction: "SELL" };
    const cash = recordListQuery(id, "CASH", filter, "token", null);
    expect(cash).not.toHaveProperty("stockMode"); expect(cash).not.toHaveProperty("tsCode"); expect(cash).not.toHaveProperty("direction");
    const closed = recordListQuery(id, "CLOSED", filter, "token", null);
    expect(closed).not.toHaveProperty("direction"); expect(closed).toHaveProperty("tsCode", "000001.SZ");
    expect(() => parseContract("CashRecordsQuery", cash)).not.toThrow();
    expect(() => parseContract("RangeRecordsQuery", closed)).not.toThrow();
  });
  it("preserves a day group's account even under ALL; history is not an authority", () => {
    const filter = { ...defaultRecordFilter("2026-09-11"), start: "2026-09-11", accountId: id, stock: { tsCode: "000001.SZ", name: "平安银行" }, direction: "SELL" };
    const query = recordListQuery("ALL", "TRADE", filter, "parent-all-token", "page-two");
    expect(query).toMatchObject({ accountMode: "SINGLE", accountId: id, readContext: "parent-all-token", cursor: "page-two", limit: 20, direction: "SELL", requestedStartDate: "2026-09-11", requestedEndDate: "2026-09-11" });
  });
});
