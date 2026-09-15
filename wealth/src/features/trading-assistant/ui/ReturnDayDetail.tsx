import { useState } from "react";
import type { DayDetail } from "../api/generatedContracts";
import { getDayContributions, getReturnDay } from "../api/returnsApi";
import { recordAccount, type RecordCategory } from "../model/recordsQuery";
import { useReturnRead } from "../model/useReturnRead";
import { positionNumber as money, positionPercent as percent, profitTone } from "../model/positionPresentation";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";

export function DayFigures({ day }: { day: DayDetail }) {
  return <div className="ta-return-day-detail">
    <div className="ta-return-day-core"><span>当天收益（元）</span><span>收益率</span>
      <strong className={profitTone(day.profitAmount)}>{money(day.profitAmount,true)}</strong><strong className={profitTone(day.profitAmount)}>{percent(day.returnPct,true)}</strong></div>
    {day.coverage.reason && <p className="ta-note" role="status">{day.coverage.reason}</p>}
    <dl className="ta-position-facts">{[["当天参与成本本金",day.capitalAmount], ["闭环已实现收益（不重复相加）",day.closedProfitAmount],
      ["当日成交佣金（已扣）",day.commissionAmount], ["当日成交印花税（已扣）",day.stampTaxAmount]].map(([title,value]) =>
        <div key={title}><dt>{title}</dt><dd className="num">{money(value)}</dd></div>)}</dl>
  </div>;
}
export function ReturnDayDetail({ selected, day, token, onChanged, onRecords, onClose }: {
  selected: string; day: string; token: string; onChanged: () => void;
  onRecords: (category: RecordCategory, day: string, token: string) => void; onClose?: () => void;
}) {
  const read = useReturnRead(`${selected}:${day}:${token}`, signal => getReturnDay(day, { ...recordAccount(selected), readContext:token }, signal), onChanged);
  const body = <>{read.loading && <p role="status">正在读取当天收益…</p>}
    {read.error && <p role="alert">当天收益暂时无法读取。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></p>}
    {read.data && <><DayFigures day={read.data} />{onClose && <DayContributions key={read.data.readContext.contextToken} selected={selected} day={day} token={read.data.readContext.contextToken} onChanged={onChanged} />}
      {onClose && <div className="ta-return-day-links">{([["TRADE","当天成交"],["CASH","资金流水"],["CLOSED","闭环交易"]] as const).map(([category,label]) =>
        <TradingAssistantAction key={category} onClick={() => onRecords(category,day,read.data!.readContext.contextToken)}>{label}</TradingAssistantAction>)}</div>}</>}
  </>;
  return onClose ? <TradingAssistantDialog variant="drawer" title={`${day} · 收益详情`} subtitle={read.data?.scope.accounts.map(a=>a.name).join("、")}
    onClose={onClose} footer={<><TradingAssistantAction onClick={onClose}>取消</TradingAssistantAction><TradingAssistantAction primary onClick={onClose}>关闭</TradingAssistantAction></>}>{body}</TradingAssistantDialog>
    : <aside className="ta-return-panel"><h2>{day}</h2>{body}</aside>;
}
function DayContributions({ selected, day, token, onChanged }: { selected: string; day: string; token: string; onChanged: () => void }) {
  const [cursors,setCursors] = useState<(string|null)[]>([null]);
  const [page,setPage] = useState(0);
  const read = useReturnRead(`${selected}:${day}:${token}:${page}`, signal => getDayContributions(day, {
    ...recordAccount(selected), readContext:token, limit:20, cursor:cursors[page] },signal),onChanged);
  return <section className="ta-return-contributions"><h3>当天股票收益贡献 · {read.data?.totalCount ?? "待计算"} 只</h3>
    {read.loading && <p role="status">读取贡献中…</p>}{read.error && <p role="alert">贡献暂不可读。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></p>}
    {read.data?.coverage.reason && <p className="ta-note">{read.data.coverage.reason}</p>}
    <div className="ta-return-contribution-rows">{read.data?.items.map(row => <div key={row.stockRef.tsCode} title={row.reason ?? undefined}>
      <span>{row.stockRef.name} · {row.stockRef.tsCode}</span><strong className={profitTone(row.profitAmount)}>{money(row.profitAmount,true)}</strong></div>)}</div>
    <div className="ta-return-contribution-pagination"><span>第 {page+1} 页 · 每页 20 只</span><TradingAssistantAction disabled={read.loading || page === 0} onClick={()=>setPage(v=>v-1)}>上一页</TradingAssistantAction>
      <TradingAssistantAction disabled={read.loading || !read.data?.nextCursor} onClick={()=>{setCursors(v=>[...v.slice(0,page+1),read.data!.nextCursor]);setPage(v=>v+1);}}>下一页</TradingAssistantAction></div>
  </section>;
}
