import { useState } from "react";
import type { RangeQuery, ReadContext, RoundDetail, RoundRecordsScope, StockRef } from "../api/generatedContracts";
import { PositionDetailDialog } from "./PositionDetailDialog";
import { getCompletedRounds, getRoundDetail } from "../api/returnsApi";
import { useReturnRead } from "../model/useReturnRead";
import { positionNumber as money, positionPercent as percent, positionQuantity as quantity, profitTone } from "../model/positionPresentation";
import { PositionMetric } from "./PositionsSummary";
import { TradingAssistantAction, TradingAssistantDialog } from "./TradingAssistantForm";

export function CompletedRounds({ query, context, onBack, onChanged, onRecords }: { query: RangeQuery; context: ReadContext;
  onBack: () => void; onChanged: () => void; onRecords: (round: RoundDetail, token: string) => void }) {
  const [page,setPage] = useState(0), [cursors,setCursors] = useState<(string|null)[]>([null]);
  const [picked,setPicked] = useState<RoundRecordsScope|null>(null);
  const token = context.contextToken;
  const read = useReturnRead(JSON.stringify([query,token,page]), async signal => {
    const data = await getCompletedRounds({ ...query, readContext:token, limit:20, cursor:cursors[page] },signal);
    // Keep the actual parent context rather than synthesizing a list version.
    return { ...data, readContext:context };
  },onChanged);
  return <section className="ta-return-panel"><div className="ta-return-toolbar"><h2>已结束整轮</h2><TradingAssistantAction onClick={onBack}>返回复盘</TradingAssistantAction></div>
    <p className="ta-note">清仓日期：{query.requestedStartDate}—{query.requestedEndDate} · 收益覆盖整轮历史</p>
    {read.loading && <p role="status">正在读取整轮…</p>}{read.error && <p role="alert">整轮暂不可读。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></p>}
    {read.data?.coverage.reason && <p className="ta-note">{read.data.coverage.reason}</p>}
    <div className="ta-completed-rows">{read.data?.items.map(row=><button key={row.roundId} onClick={()=>setPicked({ accountId:row.accountId,roundId:row.roundId })}>
      <span>{row.stockRef.name}<small>{row.stockRef.tsCode} · 第 {row.roundNumber} 轮 · {row.accountName}</small></span>
      <span>{row.openedOn}—{row.closedOn}<small>{row.openingSource === "INITIALIZATION" ? "初始化持仓" : "买入建仓"} → 日终清仓</small></span>
      <span className={profitTone(row.roundProfitAmount)}>{money(row.roundProfitAmount,true)}<small>整轮收益</small></span>
      <span className={profitTone(row.roundProfitAmount)}>{percent(row.roundReturnPct,true)}<small>整轮收益率</small></span>
    </button>)}</div>
    {read.data?.completedRoundCount === 0 && <p>所选清仓日期范围没有已结束整轮。</p>}
    <div className="ta-record-pagination"><span>{read.data?.completedRoundCount ?? "待计算"} 轮 · 第 {page+1} 页</span><div>
      <TradingAssistantAction disabled={page === 0 || read.loading} onClick={()=>setPage(v=>v-1)}>上一页</TradingAssistantAction>
      <TradingAssistantAction disabled={!read.data?.nextCursor || read.loading} onClick={()=>{setCursors(v=>[...v.slice(0,page+1),read.data!.nextCursor]);setPage(v=>v+1);}}>下一页</TradingAssistantAction></div></div>
    {picked && <HoldingRoundDetail key={picked.roundId} round={picked} token={token} onClose={()=>setPicked(null)} onChanged={onChanged} onRecords={onRecords} />}
  </section>;
}
export function HoldingRoundDetail({ round, token, onClose, onChanged, onRecords, onSell }: { round: RoundRecordsScope; token: string;
  onClose: () => void; onChanged: () => void; onRecords: (detail: RoundDetail, token: string) => void; onSell?: (accountId:string,stock:StockRef)=>void }) {
  const read = useReturnRead(JSON.stringify([round,token]), signal=>getRoundDetail(round.accountId,round.roundId,token,signal),onChanged);
  const d = read.data?.detail;
  if (d?.roundRef.status === "OPEN") return <PositionDetailDialog selected={d.accountRef.accountId} row={{ stockRef:d.stockRef }} token={read.data!.readContext.contextToken}
    expectedRoundId={d.roundRef.roundId} onClose={onClose} onRefresh={onChanged} onSell={onSell ? (account,stock)=>{onClose();onSell(account,stock);} : undefined}
    onRecords={()=>{onClose();onRecords(d,read.data!.readContext.contextToken);}} />;
  return <TradingAssistantDialog variant="round" title={d ? `${d.stockRef.name} · 第 ${d.roundRef.roundNumber} 轮` : "整轮详情"}
    subtitle={d ? `${d.stockRef.tsCode} · ${d.accountRef.name} · 已结束` : undefined} onClose={onClose}
    footer={<TradingAssistantAction onClick={onClose}>返回列表</TradingAssistantAction>}>
    {read.loading && <p role="status">正在读取整轮详情…</p>}{read.error && <p role="alert">整轮详情暂不可读。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></p>}
    {read.data?.coverage.reason && <p className="ta-note">{read.data.coverage.reason}</p>}
    {d && d.roundRef.status === "CLOSED" && <>
      <p className="ta-note">{d.openedOn} {d.openingSource === "INITIALIZATION" ? "初始化持仓" : "买入建仓"} → {d.closedOn} 日终清仓</p>
      <div className="ta-position-metrics ta-analysis-metrics ta-return-round-pair"><PositionMetric title="整轮收益" value={money(d.roundProfitAmount,true)} note="不是清仓月新增收益" tone={profitTone(d.roundProfitAmount)} /><PositionMetric title="整轮收益率" value={percent(d.roundReturnPct,true)} note="整轮收益 ÷ 累计投入" tone={profitTone(d.roundProfitAmount)} /></div>
      <div className="ta-position-metrics ta-analysis-metrics ta-return-round-pair"><PositionMetric title="累计买入投入" value={money(d.buyInvestmentAmount)} note="初始化成本已含买入费用" /><PositionMetric title="累计卖出净回款" value={money(d.sellNetProceedsAmount)} note="已扣各笔佣金和印花税" /></div>
      <h3>本轮来源</h3>{d.initializationSource && <p className="ta-note">{d.initializationSource.openedOn} 初始化：{quantity(String(d.initializationSource.quantity))} 股 × {money(d.initializationSource.costPrice)}，成本已含买入费用。</p>}
      <p className="ta-note">累计买入 {quantity(d.buyQuantity)} 股，累计卖出 {quantity(d.sellQuantity)} 股；{d.closedTradeCount} 笔独立闭环。</p>
      <p className="ta-note">整轮收益 = {money(d.sellNetProceedsAmount)} − {money(d.buyInvestmentAmount)} = {money(d.roundProfitAmount)}。最后一笔闭环收益不能替代整轮收益。</p>
      <TradingAssistantAction onClick={()=>{onClose();onRecords(d,read.data!.readContext.contextToken);}}>查看本轮闭环记录</TradingAssistantAction>
    </>}
  </TradingAssistantDialog>;
}
