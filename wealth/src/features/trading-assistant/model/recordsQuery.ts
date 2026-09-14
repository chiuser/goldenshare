import type { AccountReadQuery, CashRecordsQuery, RangeQuery, StockRef, TradeRecordsQuery } from "../api/generatedContracts";
import { beijingInputDate } from "./entryDraft";

export type RecordCategory = "TRADE" | "DAY" | "CLOSED" | "CASH";
export type RecordFilter = { start: string; end: string; stock: StockRef | null; direction: string; accountId?: string };
export const recordCategories: [RecordCategory, string][] = [["TRADE", "逐笔成交"], ["DAY", "当日汇总"], ["CLOSED", "闭环交易"], ["CASH", "资金流水"]];
export function defaultRecordFilter(today = beijingInputDate()): RecordFilter {
  return { start: today.slice(0, 7) + "-01", end: today, stock: null, direction: "" };
}
export function recordAccount(selected: string): AccountReadQuery {
  return selected === "ALL" ? { accountMode: "ALL" } : { accountMode: "SINGLE", accountId: selected };
}
export function recordRange(selected: string, filter: RecordFilter): RangeQuery {
  return { ...recordAccount(selected), requestedStartDate: filter.start, requestedEndDate: filter.end,
    stockMode: filter.stock ? "SINGLE" : "ALL", ...(filter.stock ? { tsCode: filter.stock.tsCode } : {}) };
}
export function recordListQuery(selected: string, category: RecordCategory, filter: RecordFilter, token: string, cursor: string | null): TradeRecordsQuery | CashRecordsQuery {
  const base = { ...recordAccount(filter.accountId ?? selected), requestedStartDate: filter.start, requestedEndDate: filter.end, readContext: token, limit: 20, ...(cursor ? { cursor } : {}) };
  if (category === "CASH") return { ...base, ...(filter.direction === "IN" || filter.direction === "OUT" ? { direction: filter.direction } : {}) };
  return { ...base, stockMode: filter.stock ? "SINGLE" : "ALL", ...(filter.stock ? { tsCode: filter.stock.tsCode } : {}),
    ...(category !== "CLOSED" && (filter.direction === "BUY" || filter.direction === "SELL") ? { direction: filter.direction } : {}) };
}
