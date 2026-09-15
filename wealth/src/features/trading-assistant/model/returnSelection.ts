import type { CurveQuery, StockRef } from "../api/generatedContracts";
import { recordAccount } from "./recordsQuery";

export type ReturnRange = "MONTH" | "QUARTER" | "YEAR_TO_DATE" | "YEAR" | "ALL";
export type ReturnMetric = "AMOUNT" | "RATE";
export const returnRanges: [ReturnRange, string][] = [["MONTH", "近1月"], ["QUARTER", "近3月"],
  ["YEAR_TO_DATE", "今年以来"], ["YEAR", "近1年"], ["ALL", "全部"]];

/** Civil-date controls only; no browser-side inference of business history or returns. */
export function shiftReturnMonth(date: string, months: number): string {
  const [y, m, d] = date.split("-").map(Number);
  const target = new Date(Date.UTC(y, m - 1 + months, 1));
  const last = new Date(Date.UTC(target.getUTCFullYear(), target.getUTCMonth() + 1, 0)).getUTCDate();
  target.setUTCDate(Math.min(d, last));
  return target.toISOString().slice(0, 10);
}
export function returnStart(range: ReturnRange, today: string, historyStartDate: string | null): string | null {
  if (range === "ALL") return historyStartDate;
  if (range === "YEAR_TO_DATE") return today.slice(0, 4) + "-01-01";
  return shiftReturnMonth(today, range === "MONTH" ? -1 : range === "QUARTER" ? -3 : -12);
}
export function curveSelection(selected: string, stock: StockRef | null, start: string, end: string,
  granularity: CurveQuery["granularity"], token?: string): CurveQuery {
  return { ...recordAccount(selected), stockMode:stock ? "SINGLE" : "ALL", ...(stock ? { tsCode:stock.tsCode } : {}),
    requestedStartDate:start, requestedEndDate:end, granularity, ...(token ? { readContext:token } : {}) };
}
