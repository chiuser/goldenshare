import type { TradeDayGroup, TradeRecord, TradeDetail } from "./generatedContracts";

// Validate server facts; never supply calculated values to a consumer.
export function validRecordCombination(title: unknown, value: Record<string, unknown>): boolean {
  if (title === "TradeRecord") {
    const row = value as unknown as TradeRecord;
    if ((row.direction === "BUY" || row.status === "VOID") && row.closedDataStatus !== "Empty") return false;
    return row.closedDataStatus === "Ready" ? row.closedReason === null : Boolean(row.closedReason?.trim());
  }
  if (title === "TradeDetail") {
    const detail = value as unknown as TradeDetail;
    const { record, closedTrade: closed } = detail;
    if (record.closedDataStatus !== detail.closedDataStatus || record.closedReason !== detail.reason
      || (closed !== null) !== (detail.closedDataStatus === "Ready")) return false;
    return closed === null || (record.direction === "SELL" && record.status === "ACTIVE"
      && closed.tradeId === record.tradeId && closed.sellRevision === record.revision
      && closed.accountRef.accountId === record.accountRef.accountId && closed.stockRef.tsCode === record.stockRef.tsCode);
  }
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
