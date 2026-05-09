import { useState } from "react";
import { MiniLineChart } from "../../../shared/charts/MiniLineChart";
import { formatSignedPercent } from "../../../shared/lib/formatters";
import { MetricCard } from "../../../shared/ui/MetricCard";
import { Panel } from "../../../shared/ui/Panel";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { MultiTrendPoint } from "../../../shared/model/market";
import type { MetricItem } from "../api/marketOverviewTypes";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];

interface MarketStylePanelProps {
  viewState: "loading" | "ready" | "error";
  metrics?: MetricItem[];
  chartsByRange?: Record<"1m" | "3m", MultiTrendPoint[]>;
  errorMessage?: string;
}

export function MarketStylePanel({ viewState, metrics, chartsByRange, errorMessage }: MarketStylePanelProps) {
  const [range, setRange] = useState<"1m" | "3m">("1m");
  const handleRangeChange = (value: string) => {
    if (value === "1m" || value === "3m") {
      setRange(value);
    }
  };

  return (
    <Panel
      title="市场风格"
      help="展示大盘、小盘和涨跌中位数的客观涨跌幅，不展示等权平均，也不输出风格判断建议。"
      meta={<RangeSwitch ariaLabel="市场风格时间范围" onChange={handleRangeChange} options={ranges} value={range} />}
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
          <div className="mini-metrics">
            {(metrics ?? []).map((metric) => (
              <MetricCard
                key={metric.label}
                label={metric.label}
                sub={metric.sub}
                value={<span className={metric.tone ?? "flat"}>{metric.value}</span>}
              />
            ))}
          </div>
          <MiniLineChart
            data={chartsByRange?.[range] ?? []}
            series={[
              { key: "large", name: "大盘数值", color: "var(--cs-color-info)", valueFormatter: formatSignedPercent },
              { key: "small", name: "小盘数值", color: "var(--cs-color-brand)", valueFormatter: formatSignedPercent },
              { key: "median", name: "涨跌中位数", color: "var(--cs-color-purple)", valueFormatter: formatSignedPercent },
            ]}
            valueClassBySign
            yFormatter={(value) => `${value.toFixed(1)}%`}
          />
        </>
      ) : null}
    </Panel>
  );
}
