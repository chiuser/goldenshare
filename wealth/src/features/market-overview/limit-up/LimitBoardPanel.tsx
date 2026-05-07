import { useState } from "react";
import { ComboBarChart } from "../../../shared/charts/ComboBarChart";
import { MetricCard } from "../../../shared/ui/MetricCard";
import { Panel } from "../../../shared/ui/Panel";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import type { LimitStructure, LimitStructureRow, MarketOverview } from "../api/marketOverviewTypes";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];

export function LimitBoardPanel({ overview }: { overview: MarketOverview }) {
  const [range, setRange] = useState("1m");

  return (
    <Panel
      title="涨跌停统计与分布"
      help="Review v2 调整为 2×2：左上统计卡、右上今日结构、左下历史组合柱、右下昨日结构。涨停红色、跌停绿色，今日/昨日分布结构表达统一。"
      meta={<RangeSwitch ariaLabel="涨跌停历史范围" onChange={setRange} options={ranges} value={range} />}
    >
      <div className="limit-v2-grid">
        <div className="limit-cell" aria-label="涨跌停核心统计卡">
          <div className="limit-day-title">
            <b>核心统计</b>
            <span className="day-tag">今日</span>
          </div>
          <div className="limit-stats">
            {overview.limitMetrics.map((metric) => (
              <MetricCard
                key={metric.label}
                label={metric.label}
                sub={metric.sub}
                value={<span className={metric.tone ?? "flat"}>{metric.value}</span>}
              />
            ))}
          </div>
        </div>
        <LimitStructureBlock label="今日 04-28" structure={overview.limitStructures.today} />
        <div className="limit-cell chart-cell" aria-label="历史涨跌停组合柱状图">
          <div className="sub-chart-title">
            <span>历史涨跌停组合柱图</span>
            <span className="secondary">横轴日期 / 纵轴数量</span>
          </div>
          <ComboBarChart data={overview.charts.limitHistory[range]} />
        </div>
        <LimitStructureBlock label="昨天 04-27" structure={overview.limitStructures.yesterday} />
      </div>
    </Panel>
  );
}

function LimitStructureBlock({ label, structure }: { label: string; structure: LimitStructure }) {
  return (
    <div className="limit-cell" aria-label={`${label}涨停板块分布与跌停炸板结构`}>
      <div className="limit-day-title">
        <b>涨停板块分布 + 跌停/炸板结构</b>
        <span className="day-tag">{label}</span>
      </div>
      <div className="limit-day-grid">
        <LimitRows rows={structure.up} title="涨停板块分布" />
        <LimitRows rows={structure.downBroken} title="跌停 / 炸板结构" />
      </div>
    </div>
  );
}

function LimitRows({ title, rows }: { title: string; rows: LimitStructureRow[] }) {
  return (
    <div>
      <div className="limit-map-title">{title}</div>
      <div className="distribution-graph">
        {rows.map((row) => (
          <div className="dist-row" key={row.name} title={`${row.name}：${row.count} 只`}>
            <span className="dist-label">{row.name}</span>
            <span className="dist-bar">
              <span className={`dist-fill ${row.kind}`} style={{ width: `${Math.max(8, row.ratio)}%` }} />
            </span>
            <span className={`num ${row.kind === "up" ? "up" : row.kind === "down" ? "down" : "flat"}`}>{row.count}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
