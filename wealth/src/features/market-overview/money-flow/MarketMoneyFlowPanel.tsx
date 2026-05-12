import { useState } from "react";
import { MiniLineChart } from "../../../shared/charts/MiniLineChart";
import { formatSignedAmountYi } from "../../../shared/lib/formatters";
import { Panel } from "../../../shared/ui/Panel";
import { RangeSwitch } from "../../../shared/ui/RangeSwitch";
import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { MoneyFlowOrderSizeItem } from "../api/marketOverviewTypes";
import type { MarketMoneyFlowViewModel } from "./api/marketMoneyFlowAdapter";

const ranges = [
  { value: "1m", label: "1个月" },
  { value: "3m", label: "3个月" },
];

interface MarketMoneyFlowPanelProps {
  viewState: "loading" | "ready" | "error";
  moneyFlow?: MarketMoneyFlowViewModel;
  errorMessage?: string;
}

export function MarketMoneyFlowPanel({ viewState, moneyFlow, errorMessage }: MarketMoneyFlowPanelProps) {
  const [range, setRange] = useState("1m");

  return (
    <Panel
      title="大盘资金流向"
      help="Review v4：左侧为单型资金净流向饼图，饼块显示白色结构占比，外部折线标注单型名称和净额；右侧保留历史资金流向趋势图。"
      meta={<RangeSwitch ariaLabel="大盘资金流向时间范围" onChange={setRange} options={ranges} value={range} />}
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
          <div className="fund-top">
            {(moneyFlow?.metrics ?? []).map((metric) => (
              <div className="fund-card" key={metric.label}>
                <div className="metric-label">{metric.label}</div>
                <div className={`amount ${metric.tone ?? "flat"} num`}>{metric.value}</div>
                <div className="metric-sub">{metric.sub}</div>
              </div>
            ))}
          </div>
          <div className="moneyflow-v3-body">
            <div className="order-pie-panel">
              <div className="sub-chart-title">
                <span>单型资金净流向</span>
              </div>
              <div className="pie-wrap">
                <OrderPieChart items={moneyFlow?.orderSizeItems ?? []} />
              </div>
            </div>
            <div className="moneyflow-trend-panel">
              <div className="sub-chart-title">
                <span>历史资金净流入趋势</span>
              </div>
              <MiniLineChart
                data={moneyFlow?.chartsByRange[range as "1m" | "3m"] ?? []}
                height={230}
                series={[{ key: "net", name: "净流入", color: "var(--cs-color-text-primary)", dots: true, valueFormatter: formatSignedAmountYi, width: 2.4 }]}
                valueClassBySign
                yFormatter={(value) => `${value.toFixed(0)}亿`}
                zeroCenter
              />
            </div>
          </div>
        </>
      ) : null}
    </Panel>
  );
}

function piePoint(cx: number, cy: number, r: number, angle: number) {
  const rad = ((angle - 90) * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}

function donutPath(cx: number, cy: number, r: number, ir: number, start: number, end: number) {
  const large = end - start > 180 ? 1 : 0;
  const p1 = piePoint(cx, cy, r, start);
  const p2 = piePoint(cx, cy, r, end);
  const p3 = piePoint(cx, cy, ir, end);
  const p4 = piePoint(cx, cy, ir, start);
  return `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${r} ${r} 0 ${large} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)} L ${p3.x.toFixed(2)} ${p3.y.toFixed(2)} A ${ir} ${ir} 0 ${large} 0 ${p4.x.toFixed(2)} ${p4.y.toFixed(2)} Z`;
}

function OrderPieChart({ items }: { items: MoneyFlowOrderSizeItem[] }) {
  const sum = items.reduce((total, item) => total + item.absAmount, 0) || 1;
  const cx = 180;
  const cy = 96;
  const r = 68;
  const ir = 35;
  const gapDeg = 3.1;
  let start = 0;

  const callout: Record<
    MoneyFlowOrderSizeItem["orderSize"],
    { side: "left" | "right"; band: "top" | "bottom"; lineY: number; labelX: number; elbowX?: number }
  > = {
    superLarge: { side: "right", band: "top", lineY: 44, labelX: 346 },
    small: { side: "left", band: "top", lineY: 48, labelX: 14 },
    medium: { side: "left", band: "bottom", lineY: 164, labelX: 14, elbowX: 74 },
    large: { side: "right", band: "bottom", lineY: 164, labelX: 346 },
  };

  return (
    <div className="pie-graphic" title="hover 饼块查看净额和占比">
      <svg aria-label="单型资金净流向饼图" role="img" viewBox="0 0 360 190">
        {items.map((item) => {
          const angle = (item.absAmount / sum) * 360;
          const end = start + angle;
          const mid = (start + end) / 2;
          const drawStart = start + Math.min(gapDeg / 2, angle * 0.18);
          const drawEnd = end - Math.min(gapDeg / 2, angle * 0.18);
          const color = item.direction === "inflow" ? "var(--cs-color-market-up)" : item.direction === "outflow" ? "var(--cs-color-market-down)" : "var(--cs-color-market-flat)";
          const pct = item.absAmount / sum;
          const pctText = `${(pct * 100).toFixed(1)}%`;
          const label = `${item.orderSizeName} ${formatSignedAmountYi(item.netAmount)}`;
          const labelPoint = piePoint(cx, cy, (r + ir) / 2, mid);
          const anchorPoint = piePoint(cx, cy, r + 3, mid);
          const cfg = callout[item.orderSize];
          const elbowX = cfg.elbowX ?? (cfg.side === "right" ? 274 : 86);
          const lineEndX = cfg.side === "right" ? cfg.labelX - 8 : cfg.labelX + 8;
          const textAnchor = cfg.side === "right" ? "end" : "start";
          const textY = cfg.band === "top" ? cfg.lineY - 10 : cfg.lineY + 13;
          const path = donutPath(cx, cy, r, ir, drawStart, drawEnd);
          const key = `${item.orderSize}-${start}-${end}`;
          start = end;

          return (
            <g key={key}>
              <path className="pie-slice" d={path} fill={color} />
              <polyline
                className="pie-callout-line"
                points={`${anchorPoint.x.toFixed(1)},${anchorPoint.y.toFixed(1)} ${elbowX.toFixed(1)},${cfg.lineY.toFixed(1)} ${lineEndX.toFixed(1)},${cfg.lineY.toFixed(1)}`}
              />
              <text className={`pie-callout-text ${item.direction === "inflow" ? "up" : item.direction === "outflow" ? "down" : "flat"}`} fill={color} textAnchor={textAnchor} x={cfg.labelX} y={textY.toFixed(1)}>
                {label}
              </text>
              {pct >= 0.06 ? (
                <text className="pie-slice-label" textAnchor="middle" x={labelPoint.x.toFixed(1)} y={(labelPoint.y + 4).toFixed(1)}>
                  {pctText}
                </text>
              ) : null}
            </g>
          );
        })}
        <circle className="pie-center-hole" cx={cx} cy={cy} r={ir - 1} />
      </svg>
    </div>
  );
}
