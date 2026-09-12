import type { EntryContext, RecoveryStatusDto, InitializationPositionInput, CreateAccountInput, PendingRecoveryResponse } from "./generatedContracts";

// Cross-field invariants after generated structural validation. No response shaping.
export function validCombination(title: unknown, value: Record<string, unknown>): boolean {
  if (title === "EntryContext") {
    const row = value as unknown as EntryContext;
    if (row.accountId !== row.fees.accountId) return false;
    if (row.stockRef === null) return row.quantity === null && row.availableQuantity === null;
    if ((row.quantity === null) !== (row.availableQuantity === null)) return false;
    return row.quantity === null || BigInt(row.availableQuantity!) <= BigInt(row.quantity);
  }
  if (title === "InitializationPositionInput" || title === "InitializationPosition") {
    const row = value as unknown as InitializationPositionInput;
    if (!row.clientRowId || row.availableQuantity > row.quantity) return false;
  }
  if (Array.isArray(value.initialPositions) && !value.initialPositions.includes(null)) {
    const rows = (value as unknown as CreateAccountInput).initialPositions;
    if (new Set(rows.map(row => row.tsCode)).size !== rows.length || new Set(rows.map(row => row.clientRowId)).size !== rows.length) return false;
  }
  if (title === "PendingRecoveryResponse") {
    const row = value as unknown as PendingRecoveryResponse;
    return row.pendingRequest === null || ["PROCESSING", "UNKNOWN"].includes(row.pendingRequest.outcome);
  }
  if (title === "RecoveryStatusDto") {
    const row = value as unknown as RecoveryStatusDto;
    const allowed: Record<string, readonly string[]> = {
      ACCOUNT_CREATE: ["ACCOUNT_CREATE"], ACCOUNT_FEES: ["FEES_UPDATE"],
      ACCOUNT_LEDGER: ["INITIALIZATION_CORRECT", "TRADE_CREATE", "TRADE_CORRECT", "TRADE_VOID", "CASH_FLOW_CREATE", "CASH_FLOW_CORRECT", "CASH_FLOW_VOID", "CALCULATION_RETRY"],
      RULE: ["RULE_CONDITIONS_UPDATE", "RULE_CLOSE"], RULE_CREATE: ["PLAN_CREATE", "ALERT_CREATE"],
      ROBOT: ["ROBOT_CANDIDATE_CREATE", "ROBOT_TEST", "ROBOT_CONFIRM"], NOTIFICATION: ["NOTIFICATION_RETRY"],
    };
    if (!allowed[row.scope.scopeType]?.includes(row.operationType)) return false;
    if (row.scope.scopeType === "RULE_CREATE" && row.operationType !== `${row.scope.ruleType}_CREATE`) return false;
    if ((row.outcome === "SAVED") !== (row.receipt !== null)) return false;
    if (row.rejection !== null && row.outcome !== "NOT_SAVED") return false;
    const needsTarget = ["TRADE_CORRECT", "TRADE_VOID", "CASH_FLOW_CORRECT", "CASH_FLOW_VOID"].includes(row.operationType);
    if (needsTarget !== (row.target !== null)) return false;
    if (row.target !== null) {
      if (!("accountId" in row.scope) || row.scope.accountId !== row.target.accountId) return false;
      if (!row.operationType.startsWith(row.target.kind + "_")) return false;
    }
    if (row.receipt !== null) {
      if (row.receipt.requestId !== row.requestId || row.receipt.attemptId !== row.attemptId || row.receipt.operationType !== row.operationType) return false;
      if (row.target !== null) {
        const result = row.receipt.result as unknown as Record<string, unknown>;
        if (result.accountId !== row.target.accountId || result[row.target.kind === "TRADE" ? "tradeId" : "cashFlowId"] !== row.target.recordId) return false;
      }
    }
  }
  return true;
}
