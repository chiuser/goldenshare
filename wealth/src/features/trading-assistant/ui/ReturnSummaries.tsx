import type { CalendarResponse, PositionsSummary } from "../api/generatedContracts";
import { positionNumber as money, positionPercent as percent, profitTone } from "../model/positionPresentation";
import { PositionMetric } from "./PositionsSummary";

export function ReturnSummaries({ calendar, current }: { calendar: CalendarResponse; current?: PositionsSummary }) {
  const s = calendar.monthSummary;
  const unavailable = s.dailyStatsCoverage.dataStatus !== "Ready" && s.dailyStatsCoverage.dataStatus !== "Empty";
  return <div className="ta-position-metrics ta-analysis-metrics ta-return-summary" aria-label={current ? "当前与本月收益摘要" : "收益月历摘要"}>
    {current ? <>
      <PositionMetric title="当前持仓收益率" value={percent(current.holdingReturnPct,true)} note="当前持仓轮次累计 · 含费用" tone="brand" />
      <PositionMetric title="当前持仓收益" value={money(current.holdingProfitAmount,true)} note="累计指标，不是图中某一天的值" tone={profitTone(current.holdingProfitAmount)} />
    </> : null}
    <PositionMetric title="本月收益" value={money(s.periodProfitAmount,true)} note={`收益率 ${percent(s.periodReturnPct,true)} · ${s.periodCoverage.reason || (calendar.calculatedThrough ? `截至 ${calendar.calculatedThrough}` : "尚无完整截止")}`} tone={profitTone(s.periodProfitAmount)} />
    {!current && <>
      <PositionMetric title="盈利天数" value={unavailable && !s.computedDayCount ? "待计算" : `${s.positiveDayCount} 天`} note={`已计算 ${s.computedDayCount} 天 · 持平 ${s.flatDayCount} 天${unavailable ? " · 尚未完整" : ""}`} tone="up" />
      <PositionMetric title="亏损天数" value={unavailable && !s.computedDayCount ? "待计算" : `${s.negativeDayCount} 天`} note={`最低当天收益率 ${percent(s.minDailyReturnPct,true)}${s.minDailyReturnDates.length ? ` · ${s.minDailyReturnDates.join("、")}` : ""}`} tone="down" />
    </>}
    <PositionMetric title={current ? "本月闭环收益" : "闭环交易"} value={current ? money(s.closedProfitAmount,true) : s.closedTradeCount === null ? "待计算" : `${s.closedTradeCount} 笔`}
      note={current ? `${s.closedTradeCount ?? "待计算"} 笔 · 不再叠加到本月收益` : `闭环已实现 ${money(s.closedProfitAmount,true)} · 不重复相加`} tone={current ? profitTone(s.closedProfitAmount) : "flat"} />
  </div>;
}
