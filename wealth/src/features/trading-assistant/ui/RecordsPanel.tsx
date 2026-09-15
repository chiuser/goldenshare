import { useState } from "react";
import type { RoundRecordsScope, StockRef } from "../api/generatedContracts";
import { HoldingRoundDetail } from "./CompletedRounds";
import "./returns.css";
import { defaultRecordFilter, recordCategories, type RecordCategory, type RecordFilter } from "../model/recordsQuery";
import { useRecords } from "../model/useRecords";
import { recordTable, recordCellTone, type RecordTableRow } from "../model/recordPresentation";
import { positionNumber as money, profitTone } from "../model/positionPresentation";
import { RecordFilters } from "./RecordFilters";
import { RecordDetails } from "./RecordDetails";
import type { MaintenanceRecord } from "./RecordMaintenanceForm";
import { TradingAssistantAction } from "./TradingAssistantForm";
import "./positions.css";
import "./records.css";

export type ReturnRecordsEntry = { category: RecordCategory; filter: RecordFilter; token: string; round?: RoundRecordsScope };
export function RecordsPanel({ selected, revision, onEntry, onMaintain, initial, onContextChanged, onSell }: { selected: string; revision: number; onEntry?: () => void;
  onSell?: (accountId:string,stock:StockRef)=>void;
  initial?: ReturnRecordsEntry; onContextChanged?: () => void;
  onMaintain: (source: MaintenanceRecord, action: "CORRECT" | "VOID") => void }) {
  const [category, setCategory] = useState<RecordCategory>(initial?.category ?? "TRADE");
  const [filter, setFilter] = useState(() => initial?.filter ?? defaultRecordFilter());
  const [filterVersion, setFilterVersion] = useState(0);
  const [round, setRound] = useState<RoundRecordsScope | null>(initial?.round ?? null);
  const [parents, setParents] = useState<{ category: RecordCategory; filter: RecordFilter; round: RoundRecordsScope | null }[]>([]);
  const parent = parents.at(-1);
  const [picked, setPicked] = useState<{ token: string; key: string } | null>(null);
  const [roundDetail,setRoundDetail] = useState<{ round:RoundRecordsScope;token:string }|null>(null);
  const read = useRecords(selected, category, filter, round, revision, initial && onContextChanged ? { token:initial.token, onChanged:onContextChanged } : undefined);
  const table = read.page ? recordTable(read.page) : null;
  const token = read.page?.data.readContext.contextToken;
  const chosen: RecordTableRow | undefined = table?.rows.find(r => picked !== null && picked.token === token && r.key === picked.key) ?? table?.rows[0];
  function apply(next: RecordFilter) { setFilter(next); setFilterVersion(v => v + 1); setPicked(null); }
  function rememberParent() { setParents(items => [...items, { category, filter, round }]); }
  function back() { if (parent) { setCategory(parent.category); apply(parent.filter); setRound(parent.round); } setParents(items => items.slice(0, -1)); }
  const summary = read.summary;
  return <section className="ta-records" aria-label="交易与资金记录">
    {summary && <><p className="ta-record-scope">本月概览 · {selected === "ALL" ? "全部账户" : summary.scope.accounts[0]?.name} · {summary.requestedStartDate}—{summary.requestedEndDate}（不受下方列表筛选影响）</p>
      <div className="ta-position-metrics" aria-label="本月记录摘要">
        <article className="ta-position-metric ta-position-metric--brand"><h3>本月逐笔成交</h3><strong>{summary.tradeCount} 笔</strong><small>买入 {summary.buyCount} · 卖出 {summary.sellCount}</small></article>
        <article className={`ta-position-metric ta-position-metric--${profitTone(summary.closedProfitAmount)}`}><h3>闭环交易收益</h3><strong>{money(summary.closedProfitAmount, true)}</strong><small>{summary.closedTradeCount === null ? summary.reason || "待计算" : `${summary.closedTradeCount} 笔独立闭环`}</small></article>
        <article className="ta-position-metric"><h3>资金转入</h3><strong>{money(summary.cashInAmount)}</strong><small>不计入收益率</small></article>
        <article className="ta-position-metric"><h3>资金转出</h3><strong>{money(summary.cashOutAmount)}</strong><small>不计入收益率</small></article>
      </div></>}
    <div className="ta-record-toolbar"><div className="ta-segments" aria-label="交易记录分类">{recordCategories.map(([key, label]) => <button key={key} aria-pressed={category === key} onClick={() => { setCategory(key); setRound(null); setParents([]); apply({ ...filter, direction: "", accountId: undefined }); }}>{label}</button>)}</div>
      <TradingAssistantAction primary disabled={!onEntry} onClick={onEntry}>录入交易</TradingAssistantAction></div>
    {parent ? <TradingAssistantAction onClick={back}>返回上级记录</TradingAssistantAction> : <RecordFilters key={`${category}:${filterVersion}`} category={category} initial={filter} onQuery={apply} onReset={() => apply(defaultRecordFilter())} />}
    <p className="ta-record-scope">{round ? "整轮闭环 · 完整轮次日期" : "列表范围"}：{read.page?.data.requestedStartDate ?? filter.start}—{read.page?.data.requestedEndDate ?? filter.end}
      {!round && ` · ${category === "CASH" ? "资金流水" : filter.stock?.name || "全部股票"} · ${{ BUY: "买入", SELL: "卖出", IN: "转入", OUT: "转出" }[filter.direction] || "全部方向"}`}</p>
    {read.page?.kind === "CLOSED" && <p className="ta-record-scope" aria-label="当前闭环范围汇总">{round ? "本轮" : "所选范围"}闭环 {read.page.data.summary.closedTradeCount ?? "待计算"} 笔 · 收益 {money(read.page.data.summary.closedProfitAmount,true)}{read.page.data.summary.reason ? ` · ${read.page.data.summary.reason}` : " · 完整范围，不随分页变化"}</p>}
    {read.error && <div role="alert" className="ta-position-read-error">记录暂时无法读取，未改变账户数据。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></div>}
    {read.busy && <p role="status">正在读取记录…</p>}
    {read.page?.data.coverage.reason && <p className="ta-position-coverage" role="status">{read.page.data.coverage.reason}</p>}
    <div className="ta-record-layout"><div><div className="ta-record-table-panel"><h3>{recordCategories.find(([key]) => key === category)?.[1]}明细</h3><p className="ta-note">{category === "CASH" ? "逐笔记录转入、转出，不计入收益。" : "点击一行查看详情；原始成交逐笔保留。"}</p>
      {table && <div className="ta-record-table-scroll"><table><thead><tr>{table.headings.map(h => <th key={h}>{h}</th>)}</tr></thead><tbody>{table.rows.map(row => <tr key={row.key} tabIndex={0} aria-selected={chosen?.key === row.key}
        onClick={() => setPicked({ token: token!, key: row.key })} onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setPicked({ token: token!, key: row.key }); } }}>
        {row.cells.map((cell, i) => <td key={i} title={cell} className={recordCellTone(row, i)}>{cell}</td>)}</tr>)}</tbody></table></div>}
      {table && !table.rows.length && <p role="status">{read.page?.data.coverage.dataStatus === "Empty" || read.page?.data.coverage.dataStatus === "Ready" ? "所选范围暂无记录" : "结果尚未就绪，不能确认为无记录"}</p>}
    </div><div className="ta-record-pagination"><span>第 {read.pageIndex + 1} 页 · 本页 {table?.rows.length ?? 0} 条 · 每页最多 20 条</span><div><TradingAssistantAction disabled={read.busy || !table?.rows.length || read.pageIndex === 0} onClick={read.previous}>上一页</TradingAssistantAction><TradingAssistantAction disabled={read.busy || !read.page?.data.nextCursor} onClick={read.next}>下一页</TradingAssistantAction></div></div></div>
      <aside className="ta-record-detail">{chosen && token ? <RecordDetails key={`${token}:${chosen.key}`} selection={chosen.value} token={token} onRefresh={read.refresh} onMaintain={onMaintain}
        onRoundDetail={value=>setRoundDetail({ round:value,token })}
        onGroup={group => { rememberParent(); setRound(null); setCategory("TRADE"); apply({ start: group.tradeDate, end: group.tradeDate, stock: group.stockRef, direction: group.direction, accountId: group.accountRef.accountId }); }}
        onRound={value => { rememberParent(); setCategory("CLOSED"); setRound(value); setPicked(null); }} /> : <p className="ta-note">选择一条记录查看详情</p>}</aside>
    </div>
    {roundDetail && roundDetail.token === token && <HoldingRoundDetail round={roundDetail.round} token={roundDetail.token} onClose={()=>setRoundDetail(null)} onChanged={()=>{setRoundDetail(null);read.refresh();}}
      onSell={onSell} onRecords={detail=>{rememberParent();setCategory("CLOSED");setRound({ accountId:detail.accountRef.accountId,roundId:detail.roundRef.roundId });setPicked(null);}} />}
  </section>;
}
