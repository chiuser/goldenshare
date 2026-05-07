import { useState } from "react";
import { MiniLineChart } from "../../../shared/charts/MiniLineChart";
import { formatSignedPercent } from "../../../shared/lib/formatters";
import { MetricCard } from "../../../shared/ui/MetricCard";
import { Panel } from "../../../shared/ui/Panel";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import type { MarketOverview } from "../api/marketOverviewTypes";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];

export function MarketStylePanel({ overview }: { overview: MarketOverview }) {
  const [range, setRange] = useState("1m");

  return (
    <Panel
      title="市场风格"
      help="展示大盘、小盘和涨跌中位数的客观涨跌幅，不展示等权平均，也不输出风格判断建议。"
      meta={<RangeSwitch ariaLabel="市场风格时间范围" onChange={setRange} options={ranges} value={range} />}
    >
      <div className="mini-metrics">
        {overview.styleMetrics.map((metric) => (
          <MetricCard
            key={metric.label}
            label={metric.label}
            sub={metric.sub}
            value={<span className={metric.tone ?? "flat"}>{metric.value}</span>}
          />
        ))}
      </div>
      <MiniLineChart
        data={overview.charts.style[range]}
        series={[
          { key: "large", name: "大盘数值", color: "var(--cs-color-info)", valueFormatter: formatSignedPercent },
          { key: "small", name: "小盘数值", color: "var(--cs-color-brand)", valueFormatter: formatSignedPercent },
          { key: "median", name: "涨跌中位数", color: "var(--cs-color-purple)", valueFormatter: formatSignedPercent },
        ]}
        valueClassBySign
        yFormatter={(value) => `${value.toFixed(1)}%`}
      />
      <div className="chart-note">三线：大盘数值、小盘数值、涨跌中位数；纵轴单位为百分比。</div>
    </Panel>
  );
}
