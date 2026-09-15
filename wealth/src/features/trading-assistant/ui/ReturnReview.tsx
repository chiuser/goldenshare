import type { CurveQuery, ReviewResponse } from "../api/generatedContracts";
import { getReturnReview } from "../api/returnsApi";
import { useReturnRead } from "../model/useReturnRead";
import { positionPercent as percent, profitTone } from "../model/positionPresentation";
import { PositionMetric } from "./PositionsSummary";
import { TradingAssistantAction } from "./TradingAssistantForm";
import { ReturnDates } from "./ReturnDates";

export function ReturnReview({ query, token, onChanged, onClosed, onRounds }: { query: CurveQuery; token: string; onChanged: () => void;
  onClosed: (value: ReviewResponse) => void; onRounds: (value: ReviewResponse) => void }) {
  const { granularity: _grain, ...range } = query;
  const read = useReturnRead(JSON.stringify([range, token]), signal => getReturnReview({ ...range, readContext:token },signal),onChanged);
  const stats = read.data?.dailyStats;
  return <section className="ta-return-panel ta-return-review" aria-label="所选范围复盘"><h2>所选范围复盘</h2>
    <p className="ta-note">{read.data?.scope.accounts.map(a=>a.name).join("、")} · {read.data?.scope.stockRef?.name || "全仓"} · {query.requestedStartDate}—{query.requestedEndDate}</p>
    {read.data && <p className="ta-note">{read.data.coverage.accounts.map(account=>`${read.data!.scope.accounts.find(a=>a.accountId===account.accountId)?.name}：已计算至 ${account.calculatedThroughDate ?? "尚未完成"}`).join("；")}</p>}
    {stats?.dataStatus === "Partial" && <p className="ta-note">部分数据 · 以下为已计算日期的暂定统计</p>}
    {read.loading && <p role="status">正在读取复盘…</p>}{read.error && <p role="alert">复盘暂不可读。<TradingAssistantAction onClick={read.refresh}>重新读取</TradingAssistantAction></p>}
    {stats && <><div className="ta-position-metrics ta-analysis-metrics">
      <PositionMetric title="盈利天数" value={stats.positiveDayCount?.toString() ?? "待计算"} note="按当天新增收益 > 0" tone="up" />
      <PositionMetric title="亏损天数" value={stats.negativeDayCount?.toString() ?? "待计算"} note="按当天新增收益 < 0" tone="down" />
      <PositionMetric title="持平天数" value={stats.flatDayCount?.toString() ?? "待计算"} note="有有效结果且收益为 0" />
      <PositionMetric title="最高当天收益率" value={percent(stats.maxDailyReturn?.returnPct ?? null,true)} note={<ReturnDates dates={stats.maxDailyReturn?.dates ?? []} />} tone={profitTone(stats.maxDailyReturn?.returnPct ?? null)} />
      <PositionMetric title="最低当天收益率" value={percent(stats.minDailyReturn?.returnPct ?? null,true)} note={<ReturnDates dates={stats.minDailyReturn?.dates ?? []} />} tone={profitTone(stats.minDailyReturn?.returnPct ?? null)} />
    </div><p className="ta-note">{stats.reason || `有效收益日 ${stats.computedDayCount ?? "待计算"} 天。未初始化、纯现金无持仓无交易、未来日期与缺数不计为持平日。`}</p></>}
    {read.data && <div className="ta-return-links"><TradingAssistantAction onClick={()=>onClosed(read.data!)}>查看闭环记录 · {read.data.closedTrades.closedTradeCount ?? "待计算"} 笔</TradingAssistantAction>
      <TradingAssistantAction onClick={()=>onRounds(read.data!)}>查看已结束整轮 · {read.data.completedRounds.completedRoundCount ?? "待计算"} 轮</TradingAssistantAction></div>}
    <p className="ta-note">闭环按所选范围的卖出日期查看；已结束整轮按日终清仓日期查看。两者都不与期间收益相加。</p>
  </section>;
}
