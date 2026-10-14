import { FORECAST_PERIODS, PERIOD_LABELS, type ForecastPeriod, type ForecastRows } from "./types";
import "./xxm-forecast.css";

export function XxmForecastCard({ rows, retry }: { rows: ForecastRows; retry: (period: ForecastPeriod) => void }) {
  return <section className="xxm-forecast-card" aria-label="关键高低点预判">
    <header><strong>关键高低点预判</strong><small>各周期独立计算 · 随收盘更新</small></header>
    {FORECAST_PERIODS.map(period => {
      const row = rows[period];
      const display = row.phase === "ready" ? row.response?.display : null;
      const label = display?.statusLabel ?? (row.phase === "unsupported" ? "未开放" : row.phase === "error" ? "加载失败" : "加载中");
      const target = display?.targetText ?? (row.phase === "unsupported" ? "当前环境未开放此周期" : row.phase === "error" ? "预判暂不可用" : "正在计算最近候选时点…");
      return <article className="xxm-forecast-row" data-period={period} data-phase={row.phase} data-status={row.response?.status ?? ""} key={period}>
        <div className="xxm-forecast-period"><strong>{PERIOD_LABELS[period]}</strong><span className={display && ["READY", "CONDITIONAL_ENTRY"].includes(row.response!.status) ? "candidate" : ""}>{label}</span></div>
        <b className="xxm-forecast-target">{target}</b>
        <p>{display?.conditionsText ?? (row.phase === "unsupported" ? "分钟数据能力开放后可计算。" : row.error)}</p>
        <small>{display?.asOfText ?? row.response?.display.asOfText ?? "数据截至待获取"}</small>
        {row.phase === "error" ? <button type="button" onClick={() => retry(period)} aria-label={`重试${PERIOD_LABELS[period]}关键点预判`}>重试</button> : null}
      </article>;
    })}
    <footer>前置收盘不同，结构条件也会变化；新行情到达后重新计算。</footer>
  </section>;
}
