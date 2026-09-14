import type { CashFlowRecord, ClosedTrade, TradeDayGroup, TradeRecord } from "../api/generatedContracts";
import type { RecordPage } from "./useRecords";
import { positionNumber as money, positionPercent as percent, positionQuantity as quantity, profitTone } from "./positionPresentation";

export type RecordSelection = { kind: "TRADE"; record: TradeRecord } | { kind: "CASH"; record: CashFlowRecord }
  | { kind: "DAY"; record: TradeDayGroup } | { kind: "CLOSED"; record: ClosedTrade };
export type RecordTableRow = { key: string; cells: string[]; value: RecordSelection };
export function recordCellTone(row: RecordTableRow, column: number) {
  const r = row.value;
  const amount = r.kind === "CLOSED" && (column === 8 || column === 9) ? r.record.profitAmount
    : r.kind === "CASH" && column === 3 ? r.record.netCashChange
      : (r.kind === "DAY" || r.kind === "TRADE") && column === 7 ? r.record.netCashChange : null;
  return amount === null ? "" : `ta-profit--${profitTone(amount)}`;
}
export function recordTable(page: RecordPage): { headings: string[]; rows: RecordTableRow[] } {
  if (page.kind === "CASH") return { headings: ["日期", "账户", "类型", "金额（元）", "备注"], rows: page.data.items.map(r => ({ key: r.cashFlowId,
    cells: [r.occurredOn, r.accountRef.name, r.direction === "IN" ? "资金转入" : "资金转出", money(r.netCashChange, true), r.note || "—"], value: { kind: "CASH", record: r } })) };
  if (page.kind === "CLOSED") return { headings: ["日期", "股票 / 账户", "分摊成本", "卖出价格", "数量", "佣金", "印花税", "卖出净收入", "闭环收益", "收益率"], rows: page.data.items.map(r => ({ key: r.tradeId,
    cells: [r.tradeDate, `${r.stockRef.name} · ${r.accountRef.name}`, money(r.allocatedCost), money(r.price), quantity(String(r.quantity)), money(r.commissionAmount), money(r.stampTaxAmount), money(r.netProceeds), money(r.profitAmount, true), percent(r.returnPct, true)], value: { kind: "CLOSED", record: r } })) };
  if (page.kind === "DAY") return { headings: ["日期", "股票 / 账户", "方向", "成交均价", "总数量", "佣金合计", "印花税合计", "现金变动", "笔数"], rows: page.data.items.map(r => ({ key: [r.accountRef.accountId, r.tradeDate, r.stockRef.tsCode, r.direction].join(":"),
    cells: [r.tradeDate, `${r.stockRef.name} · ${r.accountRef.name}`, r.direction === "BUY" ? "买入" : "卖出", money(r.averagePrice), quantity(r.quantity), money(r.commissionAmount), money(r.stampTaxAmount), money(r.netCashChange, true), `${r.tradeCount} 笔`], value: { kind: "DAY", record: r } })) };
  return { headings: ["日期", "股票 / 账户", "方向", "价格", "数量", "佣金", "印花税", "现金变动", "状态"], rows: page.data.items.map(r => ({ key: r.tradeId,
    cells: [r.tradeDate, `${r.stockRef.name} · ${r.accountRef.name}`, r.direction === "BUY" ? "买入" : "卖出", money(r.price), quantity(String(r.quantity)), money(r.commissionAmount), money(r.stampTaxAmount), money(r.netCashChange, true), r.status === "VOID" ? "已作废" : r.direction === "BUY" ? "已登记" : r.closedDataStatus === "Ready" ? "已闭环" : r.closedReason || "待计算"], value: { kind: "TRADE", record: r } })) };
}
export function closedFacts(r: ClosedTrade): [string, string][] {
  return [["所属账户", r.accountRef.name], ["卖出日期", r.tradeDate], ["卖出数量", quantity(String(r.quantity)) + " 股"],
    ["卖出价格", money(r.price)], ["卖出成交金额", money(r.grossAmount)], ["当日闭环单位成本", money(r.dayOpeningUnitCost)],
    ["本笔分摊成本", money(r.allocatedCost)], ["佣金", money(r.commissionAmount)], ["印花税", money(r.stampTaxAmount)],
    ["总费用", money(r.totalFeeAmount)], ["卖出净收入", money(r.netProceeds)], ["当日结束持仓", quantity(r.dayEndQuantity) + " 股"],
    ["来源流水", r.tradeId], ["日级核算组", `${r.accountRef.name} · ${r.stockRef.tsCode} · ${r.tradeDate}`], ["核算规则版本", r.calculationRuleVersion]];
}
