import type { CalendarDay, CurveResponse, DailyStats, RoundDetail } from "./generatedContracts";

export function validReturnCombination(title: unknown, value: Record<string, unknown>): boolean {
  if (["CurveQuery", "RangeQuery", "RangeRecordsQuery", "CurveResponse", "ReviewResponse"].includes(String(title)) &&
    String(value.requestedStartDate) > String(value.requestedEndDate)) return false;
  if (["CurveQuery", "RangeQuery", "RangeRecordsQuery", "CalendarQuery", "DayContributionsQuery"].includes(String(title))) {
    if (value.accountMode === "ALL" && "accountId" in value) return false;
    if (value.accountMode === "SINGLE" && !value.accountId) return false;
    if (value.stockMode === "ALL" && "tsCode" in value) return false;
    if (value.stockMode === "SINGLE" && !value.tsCode) return false;
  }
  if (title === "CalendarDay") {
    const row = value as unknown as CalendarDay;
    if (row.temporalState === "FUTURE") return [row.profitAmount, row.capitalAmount, row.returnPct,
      row.calculationState, row.reason, row.valuationAt, row.readContext].every(v => v === null);
    return row.calculationState !== null && (row.calculationState === "Ready") === (row.profitAmount !== null)
      && (row.profitAmount !== null ? row.readContext !== null : Boolean(row.reason?.trim()));
  }
  if (title === "CurveResponse") {
    const row = value as unknown as CurveResponse;
    return row.points.every((point, i) => point.periodStartDate <= point.periodEndDate &&
      (i === 0 || row.points[i - 1].periodEndDate < point.periodStartDate));
  }
  if (title === "DailyStats") {
    const row = value as unknown as DailyStats;
    const counts = [row.positiveDayCount, row.negativeDayCount, row.flatDayCount, row.computedDayCount];
    if (counts.some(n => n === null) && !counts.every(n => n === null)) return false;
    return row.computedDayCount === null || row.computedDayCount === row.positiveDayCount! + row.negativeDayCount! + row.flatDayCount!;
  }
  if (title === "RoundDetail") {
    const row = value as unknown as RoundDetail;
    if (row.accountRef.accountId !== row.roundRef.accountId || BigInt(row.sellQuantity) > BigInt(row.buyQuantity)
      || (row.openingSource === "INITIALIZATION") !== (row.initializationSource !== null)) return false;
    if (row.roundRef.status === "OPEN") return row.closedOn === null && row.roundProfitAmount === null && row.roundReturnPct === null;
    const cents = (money: string) => BigInt(money.replace(".", ""));
    return row.closedOn !== null && row.closedOn >= row.openedOn && row.sellQuantity === row.buyQuantity
      && row.roundProfitAmount !== null && row.roundReturnPct !== null
      && cents(row.roundProfitAmount) === cents(row.sellNetProceedsAmount) - cents(row.buyInvestmentAmount);
  }
  return true;
}
