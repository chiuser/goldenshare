import type { TradeDayGroup } from "./generatedContracts";

// Validate server facts; never supply calculated values to a consumer.
export function validRecordCombination(title: unknown, value: Record<string, unknown>): boolean {
  if (title !== "TradeDayGroup") return true;
  const row = value as unknown as TradeDayGroup;
  const scope = row.recordsScope;
  if (scope.accountId !== row.accountRef.accountId || scope.tsCode !== row.stockRef.tsCode
    || scope.tradeDate !== row.tradeDate || scope.direction !== row.direction || row.tradeCount < 1) return false;
  const cents = (money: string) => BigInt(money.replace(".", ""));
  const gross = cents(row.grossAmount), commission = cents(row.commissionAmount), tax = cents(row.stampTaxAmount);
  const net = row.direction === "SELL" ? gross - commission - tax : -gross - commission;
  if (cents(row.netCashChange) !== net || (row.direction === "BUY" && tax !== 0n)) return false;
  const ready = row.direction === "SELL" && row.closedDataStatus === "Ready";
  if ([row.allocatedCost, row.closedProfitAmount, row.closedReturnPct].some(v => (v !== null) !== ready)) return false;
  if (row.direction === "BUY" && row.closedDataStatus !== "Empty") return false;
  if (row.direction === "SELL" && row.closedDataStatus === "Empty") return false;
  if (!ready) return Boolean(row.reason?.trim());
  return cents(row.allocatedCost!) > 0n && cents(row.closedProfitAmount!) === net - cents(row.allocatedCost!) && row.reason === null;
}
