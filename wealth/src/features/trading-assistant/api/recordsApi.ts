import type { CashRecordsQuery, RangeQuery, RangeRecordsQuery, RoundRecordsQuery, TradeRecordsQuery } from "./generatedContracts";
import { InvalidTradingAssistantResponse, parseContract } from "./contractValidation";
import { request } from "./tradingAssistantApi";

function search(value: object) {
  const params = new URLSearchParams();
  for (const [key, item] of Object.entries(value)) if (item !== null && item !== undefined) params.set(key, String(item));
  return params.toString();
}
function verify<T extends { readContext: { contextToken: string }; scope: { accountMode: string; accounts: { accountId: string }[] } }>(
  result: T, query: { accountMode?: string; accountId?: string | null; readContext?: string | null },
): T {
  const mode = query.accountMode ?? "SINGLE";
  if (result.scope.accountMode !== mode || (mode === "SINGLE" &&
    (result.scope.accounts.length !== 1 || result.scope.accounts[0].accountId !== query.accountId))
    || (mode === "ALL" && query.readContext && result.readContext.contextToken !== query.readContext)) throw new InvalidTradingAssistantResponse();
  return result;
}
export async function getRecordsSummary(query: RangeQuery, signal: AbortSignal) {
  return verify(await request("/records/summary?" + search(parseContract("RangeQuery", query)), "RecordsSummary", { signal }), query);
}
export async function getTradeRecords(query: TradeRecordsQuery, signal: AbortSignal) {
  return verify(await request("/records/trades?" + search(parseContract("TradeRecordsQuery", query)), "TradeRecordsResponse", { signal }), query);
}
export async function getTradeDayGroups(query: TradeRecordsQuery, signal: AbortSignal) {
  return verify(await request("/records/trade-day-groups?" + search(parseContract("TradeRecordsQuery", query)), "TradeDayGroupsResponse", { signal }), query);
}
export async function getCashRecords(query: CashRecordsQuery, signal: AbortSignal) {
  return verify(await request("/records/cash-flows?" + search(parseContract("CashRecordsQuery", query)), "CashRecordsResponse", { signal }), query);
}
export async function getClosedRecords(query: RangeRecordsQuery | RoundRecordsQuery, signal: AbortSignal) {
  const validated = "roundId" in query ? parseContract("RoundRecordsQuery", query) : parseContract("RangeRecordsQuery", query);
  return verify(await request("/records/closed-trades?" + search(validated), "ClosedRecordsResponse", { signal }), query);
}
