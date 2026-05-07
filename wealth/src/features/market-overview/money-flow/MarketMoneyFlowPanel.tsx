import { useState } from "react";
import { MiniLineChart } from "../../../shared/charts/MiniLineChart";
import { formatSignedAmountYi } from "../../../shared/lib/formatters";
import { Panel } from "../../../shared/ui/Panel";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import type { MarketOverview } from "../api/marketOverviewTypes";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];

export function MarketMoneyFlowPanel({ overview }: { overview: MarketOverview }) {
  const [range, setRange] = useState("1m");

  return (
    <Panel
      title="大盘资金流向"
      help="展示今日与昨日大盘资金净流入；历史趋势以 0 为中线，正值为净流入，负值为净流出。主趋势线使用白色，Tooltip 中正红负绿。"
      meta={<RangeSwitch ariaLabel="大盘资金流向时间范围" onChange={setRange} options={ranges} value={range} />}
    >
      <div className="fund-top">
        {overview.moneyFlowMetrics.map((metric) => (
          <div className="fund-card" key={metric.label}>
            <div className="metric-label">{metric.label}</div>
            <div className={`amount ${metric.tone ?? "flat"} num`}>{metric.value}</div>
            <div className="metric-sub">{metric.sub}</div>
          </div>
        ))}
      </div>
      <MiniLineChart
        data={overview.charts.moneyFlow[range]}
        height={230}
        series={[{ key: "net", name: "净流入", color: "var(--cs-color-text-primary)", dots: true, valueFormatter: formatSignedAmountYi, width: 2.4 }]}
        valueClassBySign
        yFormatter={(value) => `${value.toFixed(0)}亿`}
        zeroCenter
      />
      <div className="chart-note">纵轴单位：亿元；0 轴居中，净流入为正，净流出为负。</div>
    </Panel>
  );
}
