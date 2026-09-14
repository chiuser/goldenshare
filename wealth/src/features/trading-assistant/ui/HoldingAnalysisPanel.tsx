import { useState } from "react";
import type { PositionsResponse } from "../api/generatedContracts";
import { useHoldingAnalysis } from "../model/useHoldingAnalysis";
import { contributionPresentation, holdingAnalysisPresentation } from "../model/holdingAnalysisPresentation";
import { PositionMetric } from "./PositionsSummary";
import { TradingAssistantAction } from "./TradingAssistantForm";
import "./holding-analysis.css";

export function HoldingAnalysisPanel({ selected, parent, onReturn, onRefresh }: {
  selected: string; parent: PositionsResponse; onReturn: () => void; onRefresh: () => void;
}) {
  const read = useHoldingAnalysis(selected, parent.readContext.contextToken, onRefresh);
  const [daily, setDaily] = useState(false);
  const data = read.data;
  const view = data && holdingAnalysisPresentation(data, parent);
  const contribution = data && contributionPresentation(daily ? data.daily : data.cumulative, daily);
  return <section className="ta-holding-analysis" aria-label="持仓分析">
    <div className="ta-analysis-heading"><p>{view?.basis ?? "读取当前持仓分析"}</p><TradingAssistantAction onClick={onReturn}>返回持仓列表</TradingAssistantAction></div>
    {read.error ? <div role="alert" className="ta-position-read-error">持仓分析暂时无法读取，未改变核算状态。<TradingAssistantAction onClick={read.retry}>重新读取分析</TradingAssistantAction></div>
      : !data || !view || !contribution ? <p role="status">正在读取持仓分析…</p> : <>
        <div className="ta-position-metrics ta-analysis-metrics" aria-label="持仓集中度">{view.metrics.map(metric => <PositionMetric key={metric.title} {...metric} />)}</div>
        {data.coverage.reason && <p role="status" className="ta-position-coverage">{data.coverage.reason}</p>}
        <div className="ta-analysis-panels">
          <section className="ta-analysis-panel" aria-label="行业分布"><h2>行业分布</h2>
            <p className="ta-analysis-note">东财三级行业 · 持仓市值 {view.stockValue} · 占比以持仓市值为分母</p>
            {view.industries.length ? <div className="ta-analysis-industries">{view.industries.map(row => <div className="ta-analysis-industry" key={row.key} title={`${row.name} · ${row.money} · ${row.percentage}`}>
              <span>{row.name}</span><span className="ta-analysis-track"><i className={row.classified ? "" : "unclassified"} style={{ width: `${row.width ?? 0}%` }} /></span>
              <strong className="num">{row.money}</strong><strong className="num">{row.percentage}</strong>
            </div>)}</div> : <p className="ta-position-empty">暂无当前持仓，现金不计入行业分布。</p>}
            <p className="ta-analysis-note">未分类仍计入持仓市值；估值不完整时不展示占比。条形使用同一刻度。</p>
          </section>
          <section className="ta-analysis-panel ta-analysis-contributions" aria-label="盈亏贡献"><h2>盈亏贡献</h2>
            <div className="ta-analysis-switch" role="group" aria-label="贡献口径"><TradingAssistantAction primary={!daily} aria-pressed={!daily} onClick={() => setDaily(false)}>当前持仓累计</TradingAssistantAction><TradingAssistantAction primary={daily} aria-pressed={daily} onClick={() => setDaily(true)}>当日</TradingAssistantAction></div>
            <div className="ta-analysis-extreme"><h3>最大正贡献</h3><p>{contribution.positive.name}</p><strong className={`num ta-profit--${contribution.positive.tone}`}>{contribution.positive.amount}</strong></div>
            <div className="ta-analysis-extreme"><h3>最大负贡献</h3><p>{contribution.negative.name}</p><strong className={`num ta-profit--${contribution.negative.tone}`}>{contribution.negative.amount}</strong></div>
            <p className="ta-analysis-structure">{contribution.structure}</p>
            <p className="ta-analysis-note">{contribution.totalLabel}{daily ? "正贡献" : "盈利"}合计 {contribution.positiveTotal} / {daily ? "负贡献" : "亏损"}合计 {contribution.negativeTotal}</p>
            {contribution.reason && <p role="status" className="ta-analysis-note">{contribution.reason}</p>}
            <p className="ta-analysis-note">{daily ? "当日：展示当前持仓当天产生的收益变化，不是截至当天累计收益。昨日持仓延续到今天，即使没有买卖，也计入当天收益；当天已清仓股票不在本模块内。" : "当前持仓累计：保留本轮已卖出净收入，扣除累计买入投入及预计卖出费用，不纳入已结束的持仓轮次。"}来源：持仓账本与已发布核算结果。</p>
          </section>
        </div>
      </>}
  </section>;
}
