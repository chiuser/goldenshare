import { type KeyboardEvent, type PointerEvent, useState } from "react";

import type { EtfActivityTrendPoint } from "../api/etfActivityApi";
import { formatTurnover, yuanToYi } from "../model/etfActivityFormatters";

const SERIES = [
  { field: "amountYuan", label: "成交额", color: "amount" },
  { field: "ma5Yuan", label: "MA5", color: "ma5" },
  { field: "ma20Yuan", label: "MA20", color: "ma20" },
] as const;

// Coordinates use the approved desktop plot as the SVG viewBox.
const WIDTH = 656;
const HEIGHT = 354;
const LEFT = 56;
const RIGHT = 638;
const TOP = 11;
const BOTTOM = 325;

function axisTicks(points: EtfActivityTrendPoint[]): number[] {
  const maximum = Math.max(0, ...points.flatMap((point) => SERIES.map(({ field }) => point[field] ?? 0)));
  const roughStep = maximum === 0 ? 1 : yuanToYi(maximum) / 4;
  const magnitude = 10 ** Math.floor(Math.log10(roughStep));
  const step = ([1, 2, 2.5, 5, 10].find((candidate) => candidate * magnitude >= roughStep) ?? 10) * magnitude;
  return [0, step, 2 * step, 3 * step, 4 * step];
}

function lineGeometry(values: (number | null)[], x: (index: number) => number, y: (value: number) => number) {
  const isolated: { x: number; y: number }[] = [];
  const commands = values.flatMap((value, index) => {
    if (value === null) return [];
    const starts = values[index - 1] == null;
    const coords = { x: x(index), y: y(value) };
    if (starts && values[index + 1] == null) isolated.push(coords);
    return `${starts ? "M" : "L"}${coords.x},${coords.y}`;
  });
  return { path: commands.join(" "), isolated };
}

interface EtfActivityChartProps {
  points: EtfActivityTrendPoint[];
  selectedDate: string | null;
  onSelectDate: (date: string) => void;
}

export function EtfActivityChart({ points, selectedDate, onSelectDate }: EtfActivityChartProps) {
  const [hoveredDate, setHoveredDate] = useState<string | null>(null);
  const ticks = axisTicks(points);
  const last = points.length - 1;
  const x = (index: number) => last === 0 ? (LEFT + RIGHT) / 2 : LEFT + index * (RIGHT - LEFT) / last;
  const plotY = (value: number) => BOTTOM - value * (BOTTOM - TOP) / ticks[ticks.length - 1];
  const y = (value: number) => plotY(yuanToYi(value));
  const activeIndex = points.findIndex((point) => point.tradeDate === (hoveredDate ?? selectedDate));
  const active = points[activeIndex];
  const labelCount = Math.min(6, points.length);
  const labels = Array.from({ length: labelCount }, (_, index) => Math.round(index * last / Math.max(1, labelCount - 1)));

  function pointUnderPointer(event: PointerEvent<SVGRectElement>) {
    const bounds = event.currentTarget.getBoundingClientRect();
    const fraction = (event.clientX - bounds.left) / bounds.width;
    return points[Math.max(0, Math.min(last, Math.round(fraction * last)))];
  }

  function selectWithKeyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const next = activeIndex < 0 ? last : Math.max(0, Math.min(last, activeIndex + (event.key === "ArrowLeft" ? -1 : 1)));
    setHoveredDate(null);
    onSelectDate(points[next].tradeDate);
  }

  return (
    <>
      <div className="etf-chart-legend" aria-label="图例">
        {SERIES.map(({ label, color }) => <span key={color} className={`etf-series-${color}`}><i aria-hidden="true" />{label}</span>)}
      </div>
      <div className="etf-chart-plot" role="group" tabIndex={0} aria-label="ETF 日成交额趋势图，使用左右方向键选择交易日"
        onKeyDown={selectWithKeyboard}>
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
          {ticks.map((value) => (
            <g key={value}>
              <line className={value === 0 ? "etf-chart-zero" : "etf-chart-grid"} x1={LEFT} x2={RIGHT} y1={plotY(value)} y2={plotY(value)} />
              <text textAnchor="end" x={46} y={plotY(value) + 4}>{Number(value.toPrecision(3))}</text>
            </g>
          ))}
          {labels.map((index) => (
            <g key={index}>
              <line className="etf-chart-grid" x1={x(index)} x2={x(index)} y1={TOP} y2={BOTTOM} />
              <text textAnchor="middle" x={x(index)} y={345}>{points[index].tradeDate.slice(5)}</text>
            </g>
          ))}
          {SERIES.map(({ field, color }) => {
            const { path, isolated } = lineGeometry(points.map((point) => point[field]), x, y);
            return (
              <g key={field} className={`etf-series-${color}`}>
                <path data-series={field} d={path} />
                {isolated.map((dot) => <circle key={dot.x} cx={dot.x} cy={dot.y} r={2.5} />)}
              </g>
            );
          })}
          {active && <line className="etf-chart-crosshair" x1={x(activeIndex)} x2={x(activeIndex)} y1={TOP} y2={BOTTOM} />}
          {SERIES.map(({ field, color }) => {
            const point = active ?? points[last];
            const value = point[field];
            return value !== null && <circle key={field} className={`etf-series-${color}`} cx={x(active ? activeIndex : last)} cy={y(value)} r={3.5} />;
          })}
          <rect className="etf-chart-hit-area" x={LEFT} y={TOP} width={RIGHT - LEFT} height={BOTTOM - TOP}
            onPointerMove={(event) => setHoveredDate(pointUnderPointer(event)?.tradeDate ?? null)}
            onPointerLeave={() => setHoveredDate(null)}
            onPointerDown={(event) => {
              const point = pointUnderPointer(event);
              if (point) onSelectDate(point.tradeDate);
            }} />
        </svg>
        {active && (
          <div className="etf-chart-tooltip" role="status" style={{ left: `clamp(0px, ${100 * x(activeIndex) / WIDTH}% ${activeIndex > last / 2 ? "- 228px" : "+ 16px"}, 100% - 210px)` }}>
            <time className="num" dateTime={active.tradeDate}>{active.tradeDate}</time>
            {SERIES.map(({ field, label, color }) => (
              <div key={field} className={`etf-series-${color}`}>
                <span><i aria-hidden="true" />{label}</span>
                <span className="num">{formatTurnover(active[field])}{active[field] === null ? "" : " 亿"}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  );
}
