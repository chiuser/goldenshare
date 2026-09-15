import { useCallback, useState } from "react";
import type { CalendarResponse, CurveQuery, PositionsResponse, ReviewResponse, StockRef } from "../api/generatedContracts";
import { getPositions } from "../api/positionsApi";
import { getReturnCalendar, getReturnCurve } from "../api/returnsApi";
import { recordAccount, type RecordCategory } from "../model/recordsQuery";
import { curveSelection, returnRanges, returnStart, type ReturnMetric, type ReturnRange } from "../model/returnSelection";
import { ReturnReadActiveContext, useReturnRead } from "../model/useReturnRead";
import { ReturnCalendarGrid } from "./ReturnCalendarGrid";
import { ReturnSummaries } from "./ReturnSummaries";
import { ReturnCurveChart } from "./ReturnCurveChart";
import { ReturnMetricTabs } from "./ReturnMetricTabs";
import { ReturnDayDetail } from "./ReturnDayDetail";
import { ReturnReview } from "./ReturnReview";
import { CompletedRounds } from "./CompletedRounds";
import { RecordsPanel, type ReturnRecordsEntry } from "./RecordsPanel";
import { TradingAssistantStockPicker } from "./TradingAssistantStockPicker";
import { TradingAssistantAction } from "./TradingAssistantForm";
import type { MaintenanceRecord } from "./RecordMaintenanceForm";
import "./positions.css";
import "./holding-analysis.css";
import "./returns.css";

export function ReturnsWorkspace({ selected, revision, view, onMaintain, onSell }: { selected: string; revision: number; view:"CURVE"|"CALENDAR";
  onSell:(accountId:string,stock:StockRef)=>void;
  onMaintain:(record:MaintenanceRecord,action:"CORRECT"|"VOID")=>void }) {
  const [generation,setGeneration] = useState(0);
  const [record,setRecord] = useState<ReturnRecordsEntry|null>(null);
  const [rounds,setRounds] = useState<ReviewResponse|null>(null);
  const changed = useCallback(()=>{setRecord(null);setRounds(null);setGeneration(v=>v+1);},[]);
  const read = useReturnRead(`${selected}:${revision}:${generation}`,async signal=>{
    const positions = await getPositions(selected,signal);
    const calendar = await getReturnCalendar({ ...recordAccount(selected),month:positions.readContext.targetThrough.slice(0,7),
      readContext:positions.readContext.contextToken },signal);
    return { positions,calendar,readContext:positions.readContext,coverage:positions.coverage };
  });
  const onClosed = (value:ReviewResponse)=>setRecord({ category:"CLOSED",token:value.readContext.contextToken,
    filter:{ start:value.requestedStartDate,end:value.requestedEndDate,stock:value.scope.stockRef,direction:"" } });
  const onDayRecords = (category:RecordCategory,day:string,token:string)=>setRecord({ category,token,
    filter:{ start:day,end:day,stock:null,direction:"" } });
  return <section aria-label="收益分析内容">
    {read.loading && <p role="status">正在读取收益依据…</p>}
    {read.error && <p role="alert">收益依据暂时无法读取。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></p>}
    {read.data && <>
      <ReturnReadActiveContext.Provider value={!record && !rounds}><div hidden={!!record || !!rounds}>{view === "CURVE" ? <CurveWorkspace key={`${selected}:${revision}:${read.data.readContext.contextToken}`} positions={read.data.positions} calendar={read.data.calendar}
        selected={selected} onChanged={changed} onClosed={onClosed} onRounds={setRounds} />
        : <CalendarWorkspace key={`${selected}:${revision}:${read.data.readContext.contextToken}`} selected={selected} initial={read.data.calendar} onChanged={changed} onRecords={onDayRecords} />}</div></ReturnReadActiveContext.Provider>
      {rounds && <ReturnReadActiveContext.Provider value={!record}><div hidden={!!record}><CompletedRounds query={{ ...recordAccount(selected),stockMode:rounds.scope.stockMode,
        ...(rounds.scope.stockRef ? { tsCode:rounds.scope.stockRef.tsCode } : {}), requestedStartDate:rounds.requestedStartDate,requestedEndDate:rounds.requestedEndDate }}
        context={rounds.readContext} onBack={()=>setRounds(null)} onChanged={changed} onRecords={(d,token)=>setRecord({ category:"CLOSED",token,
          round:{ accountId:d.accountRef.accountId,roundId:d.roundRef.roundId },filter:{ start:d.openedOn,end:d.closedOn!,stock:d.stockRef,direction:"",accountId:d.accountRef.accountId } })} /></div></ReturnReadActiveContext.Provider>}
      {record && <><TradingAssistantAction onClick={()=>setRecord(null)}>返回{rounds ? "整轮列表" : view === "CURVE" ? "范围复盘" : "收益日历"}</TradingAssistantAction>
        <RecordsPanel key={JSON.stringify(record)} selected={record.round?.accountId ?? selected} revision={revision} initial={record} onContextChanged={changed} onMaintain={onMaintain} onSell={onSell} /></>}
    </>}
  </section>;
}
function CurveWorkspace({ selected,positions,calendar,onChanged,onClosed,onRounds }: { selected:string; positions:PositionsResponse; calendar:CalendarResponse;
  onChanged:()=>void; onClosed:(value:ReviewResponse)=>void; onRounds:(value:ReviewResponse)=>void }) {
  const [stock,setStock] = useState<StockRef|null>(null), [range,setRange] = useState<ReturnRange>("MONTH");
  const [grain,setGrain] = useState<CurveQuery["granularity"]>("DAY"), [metric,setMetric] = useState<ReturnMetric>("RATE");
  const token = positions.readContext.contextToken, today = calendar.today;
  const read = useReturnRead(JSON.stringify([selected,stock,range,grain,token,today]),async signal=>{
    let start = returnStart(range,today,null);
    if (range === "ALL") {
      const probe = await getReturnCurve(curveSelection(selected,stock,today,today,grain,token),signal);
      start = probe.historyStartDate;
      if (start === null) return probe;
    }
    return getReturnCurve(curveSelection(selected,stock,start!,today,grain,token),signal);
  },onChanged);
  const data = read.data;
  return <><ReturnSummaries current={positions.summary} calendar={calendar} /><div className="ta-return-columns ta-return-columns--curve">
    <section className="ta-return-panel"><h2>收益曲线</h2><p className="ta-note">日／周／月分别看当期新增收益。</p>
      <div className="ta-return-toolbar"><TradingAssistantStockPicker value={stock} optional onChange={setStock} /><ReturnMetricTabs value={metric} onChange={setMetric} /></div>
      <div className="ta-return-toolbar"><div className="ta-return-ranges" aria-label="收益时间范围">{returnRanges.map(([key,label])=><button key={key} aria-pressed={range===key} onClick={()=>setRange(key)}>{label}</button>)}</div>
        <div className="ta-segments" aria-label="收益粒度">{([['DAY','日'],['WEEK','周'],['MONTH','月']] as const).map(([key,label])=><button key={key} aria-pressed={grain===key} onClick={()=>setGrain(key)}>{label}</button>)}</div></div>
      <p className="ta-note">周按周一至周日，月按自然月；范围复盘按所选日期统计。期内持有或清仓均计入。</p>
      {read.loading && <p role="status">正在读取曲线…</p>}{read.error && <p role="alert">收益曲线暂不可读。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></p>}
      {data && <>{data.coverage.reason && <p className="ta-note">{data.coverage.reason}</p>}<ReturnCurveChart key={`${data.requestedStartDate}:${data.granularity}:${metric}`} points={data.points} metric={metric} accounts={data.scope.accounts} />
        <p className="ta-note">区间：{data.requestedStartDate}—{data.requestedEndDate} · {data.historyStartDate ? `历史始于 ${data.historyStartDate}` : "没有可用历史"}</p></>}
    </section><aside className="ta-return-panel ta-return-rules"><h2>口径说明</h2>{[
      ["期间收益率","本期新增收益 ÷ 本期参与成本本金。日、周、月分别计算，不相加收益率。"],
      ["哪些持仓计入","期间持有或发生交易就计入；持续持有、期内清仓都保留收益变化。"],
      ["本金与资金复用","全仓回款复用去重，不重复计算本金；单股按自身持仓和买入投入计算。"],
      ["费用与资金进出","收益已考虑佣金和印花税；转入转出不算收益。"]].map(([title,text])=><section key={title}><h3>{title}</h3><p>{text}</p></section>)}</aside>
  </div>{data && <ReturnReview query={curveSelection(selected,stock,data.requestedStartDate,data.requestedEndDate,grain,token)} token={token} onChanged={onChanged} onClosed={onClosed} onRounds={onRounds} />}</>;
}
function CalendarWorkspace({ selected,initial,onChanged,onRecords }: { selected:string; initial:CalendarResponse; onChanged:()=>void;
  onRecords:(category:RecordCategory,day:string,token:string)=>void }) {
  const [month,setMonth] = useState(initial.month), [metric,setMetric] = useState<ReturnMetric>("AMOUNT");
  const [chosen,setChosen] = useState<string|null>(null), [drawer,setDrawer] = useState<string|null>(null);
  const token = initial.readContext.contextToken;
  const read = useReturnRead(`${selected}:${month}:${token}`,async signal=>{
    const value = month === initial.month ? initial : await getReturnCalendar({ ...recordAccount(selected),month,readContext:token },signal);
    return { ...value,coverage:value.monthSummary.periodCoverage };
  },onChanged);
  const calendar = read.data;
  const day = chosen ?? calendar?.days.filter(d=>d.inSelectedMonth && d.temporalState !== "FUTURE").at(-1)?.date ?? null;
  return <>{calendar && <ReturnSummaries calendar={calendar} />}{read.error && <p role="alert">日历暂不可读。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></p>}
    {read.loading && <p role="status">正在读取日历…</p>}
    <div className="ta-return-columns"><ReturnCalendarGrid calendar={calendar} month={month} metric={metric} selectedDay={day} onMonth={value=>{setMonth(value);setChosen(null);setDrawer(null);}}
      onMetric={setMetric} onDay={value=>{setChosen(value);setDrawer(value);}} />
      {day && calendar ? <ReturnDayDetail key={`${day}:${token}`} selected={selected} day={day} token={token} onChanged={onChanged} onRecords={onRecords} /> : <aside className="ta-return-panel"><p>选择日期查看收益详情</p></aside>}
    </div>{drawer && calendar && <ReturnDayDetail key={drawer} selected={selected} day={drawer} token={token} onChanged={onChanged}
      onClose={()=>setDrawer(null)} onRecords={(category,date,t)=>{setDrawer(null);onRecords(category,date,t);}} />}
  </>;
}
