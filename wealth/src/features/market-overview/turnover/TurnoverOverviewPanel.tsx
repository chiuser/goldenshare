import { useState } from "react";
import { MiniLineChart } from "../../../shared/charts/MiniLineChart";
import { MetricCard } from "../../../shared/ui/MetricCard";
import { Panel } from "../../../shared/ui/Panel";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { MarketTurnoverViewModel } from "./api/marketTurnoverAdapter";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];

interface TurnoverOverviewPanelProps {
  viewState: "loading" | "ready" | "error";
  turnover?: MarketTurnoverViewModel;
  errorMessage?: string;
}

export function TurnoverOverviewPanel({ viewState, turnover, errorMessage }: TurnoverOverviewPanelProps) {
  const [range, setRange] = useState("1m");

  return (
    <Panel
      title="成交额总览"
      help="展示当日全市场成交总额、较上一交易日变化、上一交易日成交额，以及 5 日均值。下方分别展示日内累计成交额和历史成交额。"
      meta={<RangeSwitch ariaLabel="成交额时间范围" onChange={setRange} options={ranges} value={range} />}
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
          <div className="mini-metrics cols-4">
            {(turnover?.metrics ?? []).map((metric) => (
              <MetricCard
                key={metric.label}
                label={metric.label}
                sub={metric.sub}
                value={<span className={metric.tone ?? "flat"}>{metric.value}</span>}
              />
            ))}
          </div>
          <div className="turnover-charts">
            <div>
              <div className="sub-chart-title">
                <span>当日累计成交额</span>
                <span className="secondary">09:30 / 11:30 / 15:00</span>
              </div>
              <MiniLineChart
                data={turnover?.chartsByRange?.[range as "1m" | "3m"]?.intraday ?? []}
                series={[
                  {
                    key: "amount",
                    name: "累计成交额",
                    color: "var(--cs-color-brand)",
                    dots: true,
                    valueFormatter: (v) => `${Math.round(v)}亿`,
                    width: 2.5,
                  },
                ]}
                yFormatter={(value) => `${Math.round(value)}亿`}
              />
            </div>
            <div>
              <div className="sub-chart-title">
                <span>历史成交额趋势</span>
                <span className="secondary">支持 1个月 / 3个月</span>
              </div>
              <MiniLineChart
                data={turnover?.chartsByRange?.[range as "1m" | "3m"]?.history ?? []}
                series={[
                  {
                    key: "amount",
                    name: "成交额",
                    color: "var(--cs-color-info)",
                    valueFormatter: (v) => `${Math.round(v)}亿`,
                    width: 2.3,
                  },
                ]}
                yFormatter={(value) => `${Math.round(value / 1000)}k亿`}
              />
            </div>
          </div>
        </>
      ) : null}
    </Panel>
  );
}
