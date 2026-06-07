import { useState } from "react";
import { MiniLineChart } from "../../../shared/charts/MiniLineChart";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import { MetricCard } from "../../../shared/ui/MetricCard";
import { Panel } from "../../../shared/ui/Panel";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { MultiTrendPoint } from "../../../shared/model/market";
import type { MetricItem } from "../api/marketOverviewTypes";
import type { MarketBreadthMetricsFact } from "./api/marketBreadthAdapter";

type BreadthChartMode = "counts" | "distribution";

const chartModes = [
  { value: "distribution", label: "涨跌分布" },
  { value: "counts", label: "涨跌家数" },
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

function buildDistributionBuckets(metricsFact?: MarketBreadthMetricsFact) {
  const buckets = metricsFact?.distributionBuckets;
  return [
    { key: "downGt10", label: ">10%", tone: "down", value: buckets?.downGt10Count ?? 0 },
    { key: "down7To10", label: "7~10%", tone: "down", value: buckets?.down7To10Count ?? 0 },
    { key: "down5To7", label: "5~7%", tone: "down", value: buckets?.down5To7Count ?? 0 },
    { key: "down3To5", label: "3~5%", tone: "down", value: buckets?.down3To5Count ?? 0 },
    { key: "down0To3", label: "0~3%", tone: "down", value: buckets?.down0To3Count ?? 0 },
    { label: "平盘", tone: "flat", value: metricsFact?.flatCount ?? 0 },
    { key: "up0To3", label: "0~3%", tone: "up", value: buckets?.up0To3Count ?? 0 },
    { key: "up3To5", label: "3~5%", tone: "up", value: buckets?.up3To5Count ?? 0 },
    { key: "up5To7", label: "5~7%", tone: "up", value: buckets?.up5To7Count ?? 0 },
    { key: "up7To10", label: "7~10%", tone: "up", value: buckets?.up7To10Count ?? 0 },
    { key: "upGt10", label: ">10%", tone: "up", value: buckets?.upGt10Count ?? 0 },
  ] as const;
}

function BreadthDistributionChart({ metricsFact }: { metricsFact?: MarketBreadthMetricsFact }) {
  const buckets = buildDistributionBuckets(metricsFact);
  const maxValue = Math.max(...buckets.map((bucket) => bucket.value), 1);

  return (
    <div aria-label="涨跌分布分桶柱状图" className="breadth-distribution-chart chart-box" role="img">
      <div className="breadth-distribution-bars">
        {buckets.map((bucket, index) => {
          const barHeight = Math.max(4, (bucket.value / maxValue) * 74);
          return (
            <div className="breadth-distribution-bucket" data-testid="breadth-distribution-bucket" key={`${bucket.tone}-${bucket.label}-${index}`}>
              <div className="breadth-distribution-bar-track">
                <div className="breadth-distribution-bar-stack">
                  <div className={`breadth-distribution-value ${bucket.tone}`}>{bucket.value}</div>
                  <div
                    className={`breadth-distribution-bar ${bucket.tone}`}
                    style={{ height: `${barHeight}%` }}
                  />
                </div>
              </div>
              <div className="breadth-distribution-label">{bucket.label}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

interface MarketBreadthPanelProps {
  viewState: "loading" | "ready" | "error";
  metrics?: MetricItem[];
  chartsByRange?: Record<"1m" | "3m", MultiTrendPoint[]>;
  metricsFact?: MarketBreadthMetricsFact;
  errorMessage?: string;
}

export function MarketBreadthPanel({
  viewState,
  metrics,
  chartsByRange,
  metricsFact,
  errorMessage,
}: MarketBreadthPanelProps) {
  const [chartMode, setChartMode] = useState<BreadthChartMode>("distribution");

  return (
    <Panel
      title="涨跌分布"
      help="当前日展示上涨、下跌、平盘家数；历史趋势只展示上涨家数和下跌家数，不展示平盘趋势线。"
      meta={
        <RangeSwitch
          ariaLabel="涨跌分布图表模式"
          onChange={(value) => setChartMode(value as BreadthChartMode)}
          options={chartModes}
          value={chartMode}
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
          {chartMode === "counts" ? (
            <MiniLineChart
              data={chartsByRange?.["1m"] ?? []}
              yMin={0}
              yMax={6000}
              yTickValues={BREADTH_AXIS_TICKS}
              series={[
                { key: "up", name: "上涨家数", color: "var(--cs-color-market-up)", dots: true, valueFormatter: (v) => `${Math.round(v)} 家` },
                { key: "down", name: "下跌家数", color: "var(--cs-color-market-down)", dots: true, valueFormatter: (v) => `${Math.round(v)} 家` },
              ]}
            />
          ) : (
            <BreadthDistributionChart metricsFact={metricsFact} />
          )}
        </>
      ) : null}
    </Panel>
  );
}
