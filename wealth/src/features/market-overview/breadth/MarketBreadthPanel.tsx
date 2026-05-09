import { useState } from "react";
import { MiniLineChart } from "../../../shared/charts/MiniLineChart";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import { MetricCard } from "../../../shared/ui/MetricCard";
import { Panel } from "../../../shared/ui/Panel";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { MultiTrendPoint } from "../../../shared/model/market";
import type { MetricItem } from "../api/marketOverviewTypes";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];
const BREADTH_AXIS_TICKS = [0, 1500, 3000, 4500, 6000];

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

interface MarketBreadthPanelProps {
  viewState: "loading" | "ready" | "error";
  metrics?: MetricItem[];
  chartsByRange?: Record<"1m" | "3m", MultiTrendPoint[]>;
  errorMessage?: string;
}

export function MarketBreadthPanel({ viewState, metrics, chartsByRange, errorMessage }: MarketBreadthPanelProps) {
  const [range, setRange] = useState<"1m" | "3m">("1m");

  return (
    <Panel
      title="涨跌分布"
      help="当前日展示上涨、下跌、平盘家数；历史趋势只展示上涨家数和下跌家数，不展示平盘趋势线。"
      meta={
        <RangeSwitch
          ariaLabel="涨跌分布时间范围"
          onChange={(value) => setRange(value as "1m" | "3m")}
          options={ranges}
          value={range}
        />
      }
    >
      {viewState === "loading" ? (
        <div className="summary-state-wrap">
          <SkeletonBlock />
        </div>
      ) : null}
      {viewState === "error" ? (
        <div className="summary-state-wrap">
          <div className="state-block error-box">
            <strong>error</strong>
            <br />
            <span>{errorMessage ?? "请求超时，请稍后重试。"}</span>
          </div>
        </div>
      ) : null}
      {viewState === "ready" ? (
        <>
          <MetricGrid metrics={metrics ?? []} />
          <MiniLineChart
            data={chartsByRange?.[range] ?? []}
            yMin={0}
            yMax={6000}
            yTickValues={BREADTH_AXIS_TICKS}
            series={[
              { key: "up", name: "上涨家数", color: "var(--cs-color-market-up)", dots: true, valueFormatter: (v) => `${Math.round(v)} 家` },
              { key: "down", name: "下跌家数", color: "var(--cs-color-market-down)", dots: true, valueFormatter: (v) => `${Math.round(v)} 家` },
            ]}
          />
          <div className="chart-note">横轴：交易日期；纵轴：家数。鼠标移动显示日期、上涨家数、下跌家数。</div>
        </>
      ) : null}
    </Panel>
  );
}
