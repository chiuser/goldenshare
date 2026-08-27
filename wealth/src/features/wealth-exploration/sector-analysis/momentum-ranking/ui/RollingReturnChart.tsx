import type { KeyboardEvent, PointerEvent } from "react";

import { formatReturnPct } from "../api/sectorMomentumAdapter";
import type { SectorMomentumHistoryPointViewModel, SectorMomentumPeriod } from "../model/sectorMomentumTypes";

export const CHART_LAYOUT = {
  width: 776,
  height: 365,
  left: 58,
  right: 28,
  top: 76,
  bottom: 53,
};

interface RollingReturnChartProps {
  points: SectorMomentumHistoryPointViewModel[];
  period: SectorMomentumPeriod;
  hoverIndex: number | null;
  onHoverIndex: (index: number | null) => void;
  scopeTitle: string;
}

export function RollingReturnChart({
  points,
  period,
  hoverIndex,
  onHoverIndex,
  scopeTitle,
}: RollingReturnChartProps) {
  const values = points.flatMap((point) => point.returnPct === null ? [] : [point.returnPct]);
  const minimum = Math.min(0, ...values);
  const maximum = Math.max(0, ...values);
  const span = Math.max(maximum - minimum, 1);
  const domainMin = minimum - span * 0.08;
  const domainMax = maximum + span * 0.08;
  const ticks = buildNumberTicks(domainMin, domainMax, 5);
  const yForValue = (value: number) => CHART_LAYOUT.top
    + (domainMax - value) / (domainMax - domainMin) * plotHeight();
  const path = buildLinePath(points.map((point) => point.returnPct), yForValue);
  const active = hoverIndex === null ? null : points[hoverIndex] ?? null;

  return (
    <section className="momentum-chart-card" aria-label={`${period}日区间涨跌幅趋势`}>
      <div className="momentum-chart-title">
        <strong>{period}日区间涨跌幅趋势</strong>
        <span>每个点均按所选统计周期计算</span>
      </div>
      <svg
        aria-label={`${scopeTitle}${period}日区间涨跌幅历史趋势`}
        role="img"
        tabIndex={0}
        viewBox={`0 0 ${CHART_LAYOUT.width} ${CHART_LAYOUT.height}`}
        onKeyDown={(event) => handleChartKeyDown(event, points.length, hoverIndex, onHoverIndex)}
        onPointerLeave={() => onHoverIndex(null)}
        onPointerMove={(event) => onHoverIndex(indexFromPointer(event, points.length))}
      >
        <title>{scopeTitle}{period}日区间涨跌幅历史趋势</title>
        <desc>横轴为交易日，纵轴为区间涨跌幅，缺失日期不连线。</desc>
        {ticks.map((tick) => {
          const y = yForValue(tick);
          return (
            <g key={tick}>
              <line className={tick === 0 ? "momentum-zero-line" : "momentum-grid-line"} x1={CHART_LAYOUT.left} x2={plotRight()} y1={y} y2={y} />
              <text className="momentum-axis-label" textAnchor="end" x={CHART_LAYOUT.left - 8} y={y + 4}>{formatAxisPct(tick)}</text>
            </g>
          );
        })}
        {labelIndices(points.length).map((index) => (
          <text className="momentum-axis-label" key={points[index]!.tradeDate} textAnchor={axisAnchor(index, points.length)} x={xForIndex(index, points.length)} y={CHART_LAYOUT.height - 20}>
            {formatShortDate(points[index]!.tradeDate)}
          </text>
        ))}
        <path className="momentum-return-line" d={path} />
        {active ? <ChartHover pointIndex={hoverIndex!} pointCount={points.length} value={active.returnPct} yForValue={yForValue} /> : null}
        {points.at(-1)?.returnPct !== null && points.at(-1)?.returnPct !== undefined ? (
          <LatestValuePill
            className={(points.at(-1)!.returnPct ?? 0) >= 0 ? "up-pill" : "down-pill"}
            text={formatReturnPct(points.at(-1)!.returnPct)}
            x={xForIndex(points.length - 1, points.length)}
            y={yForValue(points.at(-1)!.returnPct!)}
          />
        ) : null}
      </svg>
    </section>
  );
}

export function xForIndex(index: number, count: number): number {
  if (count <= 1) return CHART_LAYOUT.left;
  return CHART_LAYOUT.left + index / (count - 1) * (plotRight() - CHART_LAYOUT.left);
}

export function buildLinePath(values: Array<number | null>, yForValue: (value: number) => number): string {
  let drawing = false;
  return values.map((value, index) => {
    if (value === null) {
      drawing = false;
      return "";
    }
    const command = drawing ? "L" : "M";
    drawing = true;
    return `${command}${xForIndex(index, values.length).toFixed(2)},${yForValue(value).toFixed(2)}`;
  }).filter(Boolean).join(" ");
}

export function labelIndices(count: number): number[] {
  if (count <= 0) return [];
  if (count <= 5) return Array.from({ length: count }, (_, index) => index);
  return [...new Set([0, Math.round((count - 1) * 0.25), Math.round((count - 1) * 0.5), Math.round((count - 1) * 0.75), count - 1])];
}

export function plotHeight(): number {
  return CHART_LAYOUT.height - CHART_LAYOUT.top - CHART_LAYOUT.bottom;
}

export function plotRight(): number {
  return CHART_LAYOUT.width - CHART_LAYOUT.right;
}

export function handleChartKeyDown(
  event: KeyboardEvent<SVGSVGElement>,
  count: number,
  current: number | null,
  update: (index: number | null) => void,
) {
  if (!count || !["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
  event.preventDefault();
  if (event.key === "Escape") return update(null);
  if (event.key === "Home") return update(0);
  if (event.key === "End") return update(count - 1);
  const next = current ?? (event.key === "ArrowRight" ? 0 : count - 1);
  update(Math.max(0, Math.min(count - 1, next + (event.key === "ArrowRight" ? 1 : -1))));
}

function indexFromPointer(event: PointerEvent<SVGSVGElement>, count: number): number | null {
  if (!count) return null;
  const bounds = event.currentTarget.getBoundingClientRect();
  const x = (event.clientX - bounds.left) / bounds.width * CHART_LAYOUT.width;
  if (x < CHART_LAYOUT.left || x > plotRight()) return null;
  return Math.max(0, Math.min(count - 1, Math.round((x - CHART_LAYOUT.left) / (plotRight() - CHART_LAYOUT.left) * (count - 1))));
}

function ChartHover({
  pointIndex,
  pointCount,
  value,
  yForValue,
}: {
  pointIndex: number;
  pointCount: number;
  value: number | null;
  yForValue: (value: number) => number;
}) {
  const x = xForIndex(pointIndex, pointCount);
  return (
    <g>
      <line className="momentum-crosshair" x1={x} x2={x} y1={CHART_LAYOUT.top} y2={CHART_LAYOUT.height - CHART_LAYOUT.bottom} />
      {value === null ? null : <circle className="momentum-return-point" cx={x} cy={yForValue(value)} r="4" />}
    </g>
  );
}

function LatestValuePill({ text, x, y, className }: { text: string; x: number; y: number; className: string }) {
  const width = 68;
  const left = Math.min(plotRight() - width, Math.max(CHART_LAYOUT.left, x - width));
  const top = Math.max(48, y - 30);
  return (
    <g className={`momentum-latest-pill ${className}`}>
      <rect height="24" rx="5" width={width} x={left} y={top} />
      <text className="num" textAnchor="middle" x={left + width / 2} y={top + 16}>{text}</text>
    </g>
  );
}

function buildNumberTicks(minimum: number, maximum: number, count: number): number[] {
  const step = (maximum - minimum) / (count - 1);
  return Array.from({ length: count }, (_, index) => maximum - index * step);
}

function formatAxisPct(value: number): string {
  if (Math.abs(value) < 0.005) return "0%";
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function formatShortDate(value: string): string {
  return value.slice(5);
}

function axisAnchor(index: number, count: number): "start" | "middle" | "end" {
  if (index === 0) return "start";
  if (index === count - 1) return "end";
  return "middle";
}

