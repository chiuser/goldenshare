import type { AccountReadQuery, CalendarQuery, CurveQuery, DayContributionsQuery, RangeQuery, RangeRecordsQuery, Scope } from "./generatedContracts";
import { InvalidTradingAssistantResponse, parseContract } from "./contractValidation";
import { accountPath, request } from "./tradingAssistantApi";

function search(query: object) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value !== undefined && value !== null) params.set(key, String(value));
  return params.toString();
}
function scopeMatches(scope: Scope, query: AccountReadQuery & { stockMode?: string; tsCode?: string | null }) {
  if (scope.accountMode !== query.accountMode || (query.accountMode === "SINGLE" &&
    (scope.accounts.length !== 1 || scope.accounts[0].accountId !== query.accountId)) ||
    (query.stockMode && (scope.stockMode !== query.stockMode || (scope.stockRef?.tsCode ?? null) !== (query.tsCode ?? null)))) {
    throw new InvalidTradingAssistantResponse();
  }
}
function contextMatches(token: string, query: AccountReadQuery) {
  // ALL may narrow to SINGLE through the server; its canonical token changes.
  if (query.accountMode === "ALL" && query.readContext && token !== query.readContext) throw new InvalidTradingAssistantResponse();
}
export async function getReturnCurve(query: CurveQuery, signal: AbortSignal) {
  const result = await request("/returns/curve?" + search(parseContract("CurveQuery", query)), "CurveResponse", { signal });
  scopeMatches(result.scope, query); contextMatches(result.readContext.contextToken, query);
  if (result.requestedStartDate !== query.requestedStartDate || result.requestedEndDate !== query.requestedEndDate ||
    result.granularity !== query.granularity) throw new InvalidTradingAssistantResponse();
  return result;
}
export async function getReturnReview(query: RangeQuery, signal: AbortSignal) {
  const result = await request("/returns/review?" + search(parseContract("RangeQuery", query)), "ReviewResponse", { signal });
  scopeMatches(result.scope, query); contextMatches(result.readContext.contextToken, query);
  if (result.requestedStartDate !== query.requestedStartDate || result.requestedEndDate !== query.requestedEndDate) throw new InvalidTradingAssistantResponse();
  return result;
}
export async function getReturnCalendar(query: CalendarQuery, signal: AbortSignal) {
  const result = await request("/returns/calendar?" + search(parseContract("CalendarQuery", query)), "CalendarResponse", { signal });
  contextMatches(result.readContext.contextToken, query);
  if (result.month !== query.month || (query.accountMode === "SINGLE" &&
    (result.readContext.accounts.length !== 1 || result.readContext.accounts[0].accountId !== query.accountId))) throw new InvalidTradingAssistantResponse();
  return result;
}
export async function getReturnDay(day: string, query: AccountReadQuery, signal: AbortSignal) {
  const result = await request(`/returns/days/${encodeURIComponent(day)}?` + search(parseContract("AccountReadQuery", query)), "DayDetail", { signal });
  scopeMatches(result.scope, query); contextMatches(result.readContext.contextToken, query);
  if (result.date !== day) throw new InvalidTradingAssistantResponse();
  return result;
}
export async function getDayContributions(day: string, query: DayContributionsQuery, signal: AbortSignal) {
  const result = await request(`/returns/days/${encodeURIComponent(day)}/contributions?` + search(parseContract("DayContributionsQuery", query)), "DayContributions", { signal });
  scopeMatches(result.scope, query); contextMatches(result.readContext.contextToken, query);
  if (result.date !== day) throw new InvalidTradingAssistantResponse();
  return result;
}
export async function getCompletedRounds(query: RangeRecordsQuery, signal: AbortSignal) {
  const result = await request("/holding-rounds/completed?" + search(parseContract("RangeRecordsQuery", query)), "CompletedRoundsResponse", { signal });
  scopeMatches(result.scope, query);
  if (result.closedStartDate !== query.requestedStartDate || result.closedEndDate !== query.requestedEndDate) throw new InvalidTradingAssistantResponse();
  return result;
}
export async function getRoundDetail(accountId: string, roundId: string, token: string, signal: AbortSignal) {
  parseContract("RoundRecordsScope", { accountId, roundId });
  const result = await request(accountPath(accountId) + `/holding-rounds/${encodeURIComponent(roundId)}?` + search({ readContext:token }), "RoundDetailResponse", { signal });
  if (result.readContext.accounts.length !== 1 || result.readContext.accounts[0].accountId !== accountId ||
    (result.detail && (result.detail.accountRef.accountId !== accountId || result.detail.roundRef.roundId !== roundId))) throw new InvalidTradingAssistantResponse();
  return result;
}
