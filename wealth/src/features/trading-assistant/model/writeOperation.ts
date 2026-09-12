import type { RecoveryStatusDto } from "../api/generatedContracts";
import { accountPath } from "../api/tradingAssistantApi";

export type AccountingOperation = "ACCOUNT_CREATE" | "FEES_UPDATE" | "INITIALIZATION_CORRECT" | "TRADE_CREATE"
  | "TRADE_CORRECT" | "TRADE_VOID" | "CASH_FLOW_CREATE" | "CASH_FLOW_CORRECT" | "CASH_FLOW_VOID";
export type AccountingScope = Extract<RecoveryStatusDto["scope"], { scopeType: "ACCOUNT_CREATE" | "ACCOUNT_FEES" | "ACCOUNT_LEDGER" }>;

const contracts = {
  ACCOUNT_CREATE: ["CreateAccountCommand", "AccountCreateReceipt"], FEES_UPDATE: ["UpdateFeesCommand", "FeesUpdateReceipt"],
  INITIALIZATION_CORRECT: ["CorrectInitializationCommand", "InitializationCorrectReceipt"],
  TRADE_CREATE: ["TradeCommand", "TradeCreateReceipt"], TRADE_CORRECT: ["CorrectTradeCommand", "TradeCorrectReceipt"], TRADE_VOID: ["VoidCommand", "TradeVoidReceipt"],
  CASH_FLOW_CREATE: ["CashFlowCommand", "CashCreateReceipt"], CASH_FLOW_CORRECT: ["CorrectCashFlowCommand", "CashCorrectReceipt"], CASH_FLOW_VOID: ["VoidCommand", "CashVoidReceipt"],
} as const;

export function writeOperation(operation: AccountingOperation, scope: AccountingScope, target: RecoveryStatusDto["target"] = null) {
  if ((operation === "ACCOUNT_CREATE") !== (scope.scopeType === "ACCOUNT_CREATE")
    || (operation === "FEES_UPDATE") !== (scope.scopeType === "ACCOUNT_FEES")) throw new Error("Incorrect accounting scope");
  const base = "accountId" in scope ? accountPath(scope.accountId) : "/accounts";
  const correction = operation.endsWith("_CORRECT") && operation !== "INITIALIZATION_CORRECT";
  const voided = operation.endsWith("_VOID");
  if ((correction || voided) !== (target !== null)) throw new Error("Incorrect accounting target");
  if (target && (!("accountId" in scope) || scope.accountId !== target.accountId || !operation.startsWith(target.kind + "_"))) {
    throw new Error("Incorrect accounting target identity");
  }
  let path = base;
  if (operation === "FEES_UPDATE") path += "/fees";
  else if (operation === "INITIALIZATION_CORRECT") path += "/initialization/corrections";
  else if (operation.startsWith("TRADE_")) path += "/trades";
  else if (operation.startsWith("CASH_FLOW_")) path += "/cash-flows";
  if (target) path += `/${encodeURIComponent(target.recordId)}/${voided ? "voids" : "corrections"}`;
  const [commandModel, receiptModel] = contracts[operation];
  return { operation, scope, target, path, commandModel, receiptModel, method: operation === "FEES_UPDATE" ? "PUT" as const : "POST" as const };
}

// Used only to compare immutable inputs in memory; never logged or persisted.
export function canonicalInput(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonicalInput).join(",") + "]";
  if (value !== null && typeof value === "object") return "{" + Object.keys(value).sort().map(key =>
    JSON.stringify(key) + ":" + canonicalInput((value as Record<string, unknown>)[key])).join(",") + "}";
  const encoded = JSON.stringify(value);
  if (encoded === undefined) throw new Error("Undefined input is not a command fact");
  return encoded;
}
