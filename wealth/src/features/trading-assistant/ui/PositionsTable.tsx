import { Fragment, useMemo, useState } from "react";
import type { PositionRow } from "../api/generatedContracts";
import { fixedUnits, positionNumber as number, positionPercent as percent, positionQuantity as quantity, profitTone, sortPositions, type PositionSort } from "../model/positionPresentation";
import { PositionFees } from "./PositionsSummary";
import { TradingAssistantAction } from "./TradingAssistantForm";

export function PositionsTable({ rows, onDetail }: { rows: readonly PositionRow[]; onDetail: (row: PositionRow) => void }) {
  const [sort, setSort] = useState<{ field: PositionSort; descending: boolean }>({ field: "marketValue", descending: true });
  const [expanded, setExpanded] = useState<string | null>(null);
  const ordered = useMemo(() => sortPositions(rows, sort.field, sort.descending), [rows, sort]);
  const heading = (field: PositionSort, label: string) => <th aria-sort={sort.field === field ? sort.descending ? "descending" : "ascending" : "none"}>
    <button type="button" onClick={() => setSort({ field, descending: sort.field !== field || !sort.descending })}>{label}{sort.field === field ? sort.descending ? " ↓" : " ↑" : ""}</button></th>;
  return <section className="ta-position-panel"><h2>当前持仓 <small>{rows.length} 只</small></h2>
    <div className="ta-positions-table-scroll" tabIndex={0} aria-label="完整持仓列表"><table className="ta-positions-table">
      <thead><tr><th>股票</th><th>持仓 / 可卖</th><th>动态成本</th><th>价格 / 估值时间</th>
        {heading("marketValue", "持仓市值")}<th>当日收益</th>{heading("holdingProfitAmount", "持仓收益")}{heading("holdingReturnPct", "收益率")}{heading("stockValueWeightPct", "持仓占比")}<th>操作</th></tr></thead>
      <tbody>{ordered.map(row => <Fragment key={row.stockRef.tsCode}><tr>
        <td><button className="ta-stock-link" type="button" onClick={() => onDetail(row)}>{row.stockRef.name}</button><small>{row.stockRef.tsCode} · {row.industry ?? "未分类"}</small>{row.reason && <small title={row.reason}>{row.reason}</small>}</td>
        <td>{quantity(row.quantity)}<small>可卖 {quantity(row.availableQuantity)}</small></td>
        <td>{number(row.dynamicCostPrice)}<small>总成本 {number(row.dynamicCostAmount)}</small>{row.dynamicCostAmount !== null && fixedUnits(row.dynamicCostAmount) <= 0n && <small>本金已收回</small>}</td>
        <td>{number(row.price)}<small>{row.quoteAt ? new Date(row.quoteAt).toLocaleString("sv-SE", { timeZone: "Asia/Shanghai", hour12: false }).slice(0, 16) : "估值待确认"}</small>
          {row.valuationMethod === "CONFIRMED_SUSPENSION_CARRY" && <small>停牌 · 沿用最后有效收盘价<br />价格日期 {row.priceDate} · 估值日期 {row.valuationDate}</small>}</td>
        <td>{number(row.marketValue)}</td><td className={`ta-profit--${profitTone(row.dayProfitAmount)}`}>{number(row.dayProfitAmount, true)}</td>
        <td className={`ta-profit--${profitTone(row.holdingProfitAmount)}`}>{number(row.holdingProfitAmount, true)}</td>
        <td className={`ta-profit--${profitTone(row.holdingReturnPct)}`}>{percent(row.holdingReturnPct, true)}</td><td>{percent(row.stockValueWeightPct)}</td>
        <td><div className="ta-position-row-actions"><TradingAssistantAction onClick={() => onDetail(row)}>详情 / 卖出</TradingAssistantAction>
          <button type="button" aria-expanded={expanded === row.stockRef.tsCode} onClick={() => setExpanded(expanded === row.stockRef.tsCode ? null : row.stockRef.tsCode)}>预计费用</button></div></td>
      </tr>{expanded === row.stockRef.tsCode && <tr><td colSpan={10}><PositionFees row={row} /></td></tr>}</Fragment>)}</tbody>
    </table></div>
    {!rows.length && <p className="ta-position-empty">当前没有股票持仓</p>}
  </section>;
}
