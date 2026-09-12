import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { getAuthEpoch } from "../../../features/auth/model/authStorage";
import { InvalidTradingAssistantResponse, parseContract } from "./contractValidation";
import type { Contracts, TradingAssistantErrorDto, RecoveryStatusDto } from "./generatedContracts";

export const READ_TIMEOUT_MS = 8000;
export const WRITE_TIMEOUT_MS = 12000;
const BASE = "/api/v1/wealth/market/trading-assistant";

export class TradingAssistantApiError extends Error {
  constructor(public readonly details: TradingAssistantErrorDto) { super(details.message); }
}
export class SaveOutcomeUnknown extends Error {
  constructor() { super("保存结果尚未确认，请核对原操作"); }
}

export async function request<K extends keyof Contracts>(path: string, model: K,
  options: { method?: "GET" | "POST" | "PUT"; body?: unknown; signal?: AbortSignal; write?: boolean } = {}): Promise<Contracts[K]> {
  const epoch = getAuthEpoch();
  const controller = new AbortController();
  let rejectAbort!: (error: DOMException) => void;
  const cancellation = new Promise<never>((_, reject) => { rejectAbort = reject; });
  const aborted = () => { controller.abort(); rejectAbort(new DOMException("Request aborted", "AbortError")); };
  options.signal?.addEventListener("abort", aborted, { once: true });
  if (options.signal?.aborted) aborted();
  const timer = window.setTimeout(aborted, options.write ? WRITE_TIMEOUT_MS : READ_TIMEOUT_MS);
  try {
    return await Promise.race([cancellation, (async () => {
    const response = await wealthFetch(BASE + path, { method: options.method ?? "GET", signal: controller.signal,
      headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body), cache: "no-store" },
    { replayAfterRefresh: !options.write });
    if (epoch !== getAuthEpoch() || controller.signal.aborted) throw new DOMException("Stale request", "AbortError");
    const value: unknown = await response.json();
    if (epoch !== getAuthEpoch() || controller.signal.aborted) throw new DOMException("Stale request", "AbortError");
    if (!response.ok) throw new TradingAssistantApiError(parseContract("TradingAssistantErrorDto", value));
    return parseContract(model, value);
    })()]);
  } catch (error) {
    if (epoch !== getAuthEpoch()) throw new DOMException("Previous login", "AbortError");
    if (error instanceof TradingAssistantApiError) throw error;
    if (options.write) throw new SaveOutcomeUnknown();
    throw error;
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener("abort", aborted);
  }
}

export const accountPath = (accountId: string) => `/accounts/${encodeURIComponent(accountId)}`;
export const getAccounts = (signal?: AbortSignal) => request("/accounts", "AccountsResponse", { signal });
export const getDefaults = (signal?: AbortSignal) => request("/account-initialization/defaults", "InitializationDefaults", { signal });
export const getFees = (accountId: string, signal?: AbortSignal) => request(accountPath(accountId) + "/fees", "FeeSettingsDto", { signal });
export const getInitialization = (accountId: string, signal?: AbortSignal) => request(accountPath(accountId) + "/initialization", "InitializationDetail", { signal });
export async function getTradeDetail(accountId: string, tradeId: string, signal?: AbortSignal) {
  const detail = await request(`/records/trades/${encodeURIComponent(tradeId)}`, "TradeDetail", { signal });
  if (detail.record.accountRef.accountId !== accountId || detail.record.tradeId !== tradeId) throw new InvalidTradingAssistantResponse();
  return detail;
}
export async function getCashDetail(accountId: string, cashFlowId: string, signal?: AbortSignal) {
  const detail = await request(`/records/cash-flows/${encodeURIComponent(cashFlowId)}`, "CashFlowDetail", { signal });
  if (detail.record.accountRef.accountId !== accountId || detail.record.cashFlowId !== cashFlowId) throw new InvalidTradingAssistantResponse();
  return detail;
}
export const getEntryContext = (accountId: string, occurredOn: string, tsCode?: string, signal?: AbortSignal) => {
  const query = new URLSearchParams({ occurredOn });
  if (tsCode) query.set("tsCode", tsCode);
  return request(accountPath(accountId) + "/entry-context?" + query, "EntryContext", { signal });
};
export async function getRecovery(requestId: string, signal?: AbortSignal) {
  const status = await request(`/write-requests/${encodeURIComponent(requestId)}`, "RecoveryStatusDto", { signal });
  if (status.requestId !== requestId) throw new InvalidTradingAssistantResponse();
  return status;
}
export async function getRecoverableInput(status: RecoveryStatusDto, signal?: AbortSignal) {
  if (status.outcome !== "NOT_SAVED" || !status.inputRetained) throw new InvalidTradingAssistantResponse();
  const recovered = await request(`/write-requests/${encodeURIComponent(status.requestId)}/input`, "RecoveryInputResponse", { signal });
  const target = recovered.target;
  if (recovered.requestId !== status.requestId || recovered.operationType !== status.operationType
    || (target === null) !== (status.target === null)
    || (target && status.target && (target.accountId !== status.target.accountId
      || target.kind !== status.target.kind || target.recordId !== status.target.recordId))) throw new InvalidTradingAssistantResponse();
  return recovered;
}
export const getPending = (scopeType: "ACCOUNT_CREATE" | "ACCOUNT_FEES" | "ACCOUNT_LEDGER", accountId?: string, signal?: AbortSignal) => {
  const query = new URLSearchParams({ scopeType });
  if (accountId) query.set("accountId", accountId);
  return request("/write-requests/pending?" + query, "PendingRecoveryResponse", { signal });
};
