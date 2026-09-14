import { getAuthEpoch } from "../../auth/model/authStorage";
import type { AccountReadQuery } from "./generatedContracts";
import { InvalidTradingAssistantResponse } from "./contractValidation";
import { accountPath, request } from "./tradingAssistantApi";

function scopeQuery(selected: string, token?: string) {
  const scope: AccountReadQuery = selected === "ALL" ? { accountMode: "ALL" } : { accountMode: "SINGLE", accountId: selected };
  const params = new URLSearchParams({ accountMode: scope.accountMode });
  if (scope.accountId) params.set("accountId", scope.accountId);
  if (token) params.set("readContext", token);
  return params;
}
export async function getPositions(selected: string, signal: AbortSignal) {
  const result = await request("/positions?" + scopeQuery(selected), "PositionsResponse", { signal });
  if (result.scope.accountMode !== (selected === "ALL" ? "ALL" : "SINGLE")
    || (selected !== "ALL" && (result.scope.accounts.length !== 1 || result.scope.accounts[0].accountId !== selected))) {
    throw new InvalidTradingAssistantResponse();
  }
  return result;
}
export async function getPositionDetail(selected: string, code: string, token: string, signal: AbortSignal) {
  const result = await request(`/positions/${encodeURIComponent(code)}?` + scopeQuery(selected, token), "PositionDetail", { signal });
  if (result.stockRef.tsCode !== code || result.scope.accountMode !== (selected === "ALL" ? "ALL" : "SINGLE")
    || (selected !== "ALL" && (result.scope.accounts.length !== 1 || result.scope.accounts[0].accountId !== selected))) {
    throw new InvalidTradingAssistantResponse();
  }
  return result;
}
export async function getCalculationStatus(accountId: string, signal: AbortSignal) {
  const result = await request(accountPath(accountId) + "/calculation-status", "CalculationStatus", { signal });
  if (result.accountId !== accountId) throw new InvalidTradingAssistantResponse();
  return result;
}
export async function getPositionsAnalysis(selected: string, token: string, signal: AbortSignal) {
  const result = await request("/positions/analysis?" + scopeQuery(selected, token), "PositionsAnalysis", { signal });
  if (result.readContext.contextToken !== token || result.scope.accountMode !== (selected === "ALL" ? "ALL" : "SINGLE")
    || (selected !== "ALL" && (result.scope.accounts.length !== 1 || result.scope.accounts[0].accountId !== selected))) {
    throw new InvalidTradingAssistantResponse();
  }
  return result;
}
export const positionsReadApi = { positions: getPositions, status: getCalculationStatus, epoch: getAuthEpoch };
