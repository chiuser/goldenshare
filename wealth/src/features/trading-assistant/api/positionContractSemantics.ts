import type { Allocation, AllocationSlice, PositionAccountRound, PositionRow, PositionsResponse, PositionsSummary } from "./generatedContracts";
import { fixedUnits } from "../model/positionPresentation";

/** Matches backend cross-field validation; assertions only, never response repair. */
export function validPositionCombination(title: unknown, value: Record<string, unknown>): boolean {
  if (title === "PositionRow" || title === "PositionAccountRound") {
    const row = value as unknown as PositionRow | PositionAccountRound;
    if (row.availableQuantity !== null && BigInt(row.availableQuantity) > BigInt(row.quantity)) return false;
    if (row.dataStatus === "Ready" && row.availableQuantity === null) return false;
    const dates = [row.valuationDate, row.priceDate, row.valuationMethod];
    if (dates.some(item => item === null)) {
      if (!dates.every(item => item === null) || row.price !== null) return false;
    } else if (row.price === null || (row.valuationMethod === "SAME_DAY_CLOSE" ? row.priceDate !== row.valuationDate : row.priceDate! >= row.valuationDate!)) return false;
    const fees = [row.estimatedSellCommission, row.estimatedStampTax, row.estimatedTotalFeeAmount];
    if (fees.some(item => item === null)) { if (row.estimatedTotalFeeAmount !== null) return false; }
    else if (fixedUnits(fees[0]!) + fixedUnits(fees[1]!) !== fixedUnits(fees[2]!)) return false;
    if ("accountRounds" in row) {
      if (new Set(row.accountRounds.map(item => item.accountId + "/" + item.roundId)).size !== row.accountRounds.length) return false;
      if (row.dataStatus === "Ready" && (!row.accountRounds.length || [row.dynamicCostPrice, row.dynamicCostAmount, row.price, row.marketValue,
        ...fees, row.estimatedNetProceeds, row.holdingProfitAmount, row.holdingReturnPct].some(item => item === null))) return false;
    } else if (row.roundRef.status !== "OPEN" || row.roundRef.accountId !== row.accountRef.accountId) return false;
  }
  if (title === "PositionsSummary") {
    const row = value as unknown as PositionsSummary;
    if ((row.stockMarketValue === null || fixedUnits(row.stockMarketValue) === 0n) && (row.top3WeightPct !== null || row.largestPosition !== null)) return false;
    if ((row.totalAssets === null || fixedUnits(row.totalAssets) === 0n) && (row.cashWeightPct !== null || row.stockAssetWeightPct !== null)) return false;
    if (row.cashAmount === null && row.cashWeightPct !== null || row.stockMarketValue === null && row.stockAssetWeightPct !== null) return false;
  }
  if (title === "AllocationSlice") {
    const row = value as unknown as AllocationSlice;
    if ((row.kind === "STOCK") !== (row.stockRef !== null)) return false;
    if (row.kind === "OTHER") {
      if (!row.members.length || new Set(row.members.map(member => member.stockRef.tsCode)).size !== row.members.length) return false;
      if (row.members.reduce((sum, member) => sum + fixedUnits(member.marketValue), 0n) !== fixedUnits(row.marketValue)) return false;
    } else if (row.members.length) return false;
  }
  if (title === "Allocation") {
    const row = value as unknown as Allocation;
    if ((row.stockMarketValue === null || fixedUnits(row.stockMarketValue) === 0n) && row.stockValueSlices !== null) return false;
    if ((row.totalAssets === null || fixedUnits(row.totalAssets) === 0n) && row.totalAssetSlices !== null) return false;
    if (row.stockValueSlices?.some(slice => slice.kind === "CASH")) return false;
  }
  if (title === "PositionsResponse") {
    const row = value as unknown as PositionsResponse;
    if (new Set(row.items.map(item => item.stockRef.tsCode)).size !== row.items.length) return false;
  }
  return true;
}
