import type { SectorMomentumHistoryPointViewModel } from "../model/sectorMomentumTypes";
import {
  buildLinePath,
  CHART_LAYOUT,
  handleChartKeyDown,
  labelIndices,
  plotHeight,
  plotRight,
  xForIndex,
} from "./RollingReturnChart";

interface HistoricalRankChartProps {
  points: SectorMomentumHistoryPointViewModel[];
  hoverIndex: number | null;
  onHoverIndex: (index: number | null) => void;
  scopeTitle: string;
}

export function HistoricalRankChart({ points, hoverIndex, onHoverIndex, scopeTitle }: HistoricalRankChartProps) {
  const maximum = Math.max(1, ...points.map((point) => point.totalCount));
  const yForRank = (rank: number) => CHART_LAYOUT.top + (rank - 1) / Math.max(1, maximum - 1) * plotHeight();
  const ticks = rankTicks(maximum);
  const path = buildLinePath(points.map((point) => point.strengthRank), yForRank);
  const active = hoverIndex === null ? null : points[hoverIndex] ?? null;
  return (
    <section className="momentum-chart-card" aria-label={`${scopeTitle}强度排名趋势`}>
      <div className="momentum-chart-title">
        <strong>{scopeTitle}强度排名趋势</strong>
        <span>第 1 名位于图表顶部</span>
      </div>
      <svg
        aria-label={`${scopeTitle}历史强度排名趋势`}
        role="img"
        tabIndex={0}
        viewBox={`0 0 ${CHART_LAYOUT.width} ${CHART_LAYOUT.height}`}
        onKeyDown={(event) => handleChartKeyDown(event, points.length, hoverIndex, onHoverIndex)}
        onPointerLeave={() => onHoverIndex(null)}
        onPointerMove={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          const x = (event.clientX - bounds.left) / bounds.width * CHART_LAYOUT.width;
          if (x < CHART_LAYOUT.left || x > plotRight() || !points.length) return onHoverIndex(null);
          onHoverIndex(Math.max(0, Math.min(points.length - 1, Math.round((x - CHART_LAYOUT.left) / (plotRight() - CHART_LAYOUT.left) * (points.length - 1)))));
        }}
      >
        <title>{scopeTitle}历史强度排名趋势</title>
        <desc>横轴为交易日，纵轴为同组强度排名，第 1 名位于顶部，缺失日期不连线。</desc>
        {ticks.map((tick) => {
          const y = yForRank(tick);
          return (
            <g key={tick}>
              <line className="momentum-grid-line" x1={CHART_LAYOUT.left} x2={plotRight()} y1={y} y2={y} />
              <text className="momentum-axis-label" textAnchor="end" x={CHART_LAYOUT.left - 8} y={y + 4}>{tick}</text>
            </g>
          );
        })}
        {labelIndices(points.length).map((index) => (
          <text className="momentum-axis-label" key={points[index]!.tradeDate} textAnchor={index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"} x={xForIndex(index, points.length)} y={CHART_LAYOUT.height - 20}>
            {points[index]!.tradeDate.slice(5)}
          </text>
        ))}
        <path className="momentum-rank-line" d={path} />
        {active ? (
          <g>
            <line className="momentum-crosshair" x1={xForIndex(hoverIndex!, points.length)} x2={xForIndex(hoverIndex!, points.length)} y1={CHART_LAYOUT.top} y2={CHART_LAYOUT.height - CHART_LAYOUT.bottom} />
            {active.strengthRank === null ? null : <circle className="momentum-rank-point" cx={xForIndex(hoverIndex!, points.length)} cy={yForRank(active.strengthRank)} r="4" />}
          </g>
        ) : null}
        {points.at(-1)?.strengthRank ? (
          <g className="momentum-latest-pill rank-pill">
            <rect height="24" rx="5" width="54" x={plotRight() - 58} y={Math.max(48, yForRank(points.at(-1)!.strengthRank!) - 30)} />
            <text className="num" textAnchor="middle" x={plotRight() - 31} y={Math.max(64, yForRank(points.at(-1)!.strengthRank!) - 14)}>第 {points.at(-1)!.strengthRank} 名</text>
          </g>
        ) : null}
      </svg>
    </section>
  );
}

function rankTicks(maximum: number): number[] {
  return [...new Set([1, Math.max(1, Math.round(maximum * 0.25)), Math.max(1, Math.round(maximum * 0.5)), Math.max(1, Math.round(maximum * 0.75)), maximum])].sort((a, b) => a - b);
}

