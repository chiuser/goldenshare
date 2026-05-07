import { useState } from "react";
import { MiniLineChart } from "../../../shared/charts/MiniLineChart";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import { MetricCard } from "../../../shared/ui/MetricCard";
import { Panel } from "../../../shared/ui/Panel";
import type { MarketOverview, MetricItem } from "../api/marketOverviewTypes";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];

function MetricGrid({ metrics }: { metrics: MetricItem[] }) {
  return (
    <div className="mini-metrics">
      {metrics.map((metric) => (
        <MetricCard
          key={metric.label}
          label={metric.label}
          sub={metric.sub}
          value={<span className={metric.tone ?? "flat"}>{metric.value}</span>}
        />
      ))}
    </div>
  );
}

export function MarketBreadthPanel({ overview }: { overview: MarketOverview }) {
  const [range, setRange] = useState("1m");

  return (
    <Panel
      title="涨跌分布"
      help="当前日展示上涨、下跌、平盘家数；历史趋势只展示上涨家数和下跌家数，不展示平盘趋势线。"
      meta={<RangeSwitch ariaLabel="涨跌分布时间范围" onChange={setRange} options={ranges} value={range} />}
    >
      <MetricGrid metrics={overview.breadthMetrics} />
      <MiniLineChart
        data={overview.charts.breadth[range]}
        series={[
          { key: "up", name: "上涨家数", color: "var(--cs-color-market-up)", dots: true, valueFormatter: (v) => `${Math.round(v)} 家` },
          { key: "down", name: "下跌家数", color: "var(--cs-color-market-down)", dots: true, valueFormatter: (v) => `${Math.round(v)} 家` },
        ]}
      />
      <div className="chart-note">横轴：交易日期；纵轴：家数。鼠标移动显示日期、上涨家数、下跌家数。</div>
    </Panel>
  );
}
