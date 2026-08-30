import { useMemo, useState } from "react";

import { buildScatterGeometry } from "../model/sectorPriceVolumeGeometry";
import type { SectorPriceVolumeController } from "../model/useSectorPriceVolumeController";

export function PriceVolumeScatterPlot({ controller }: { controller: SectorPriceVolumeController }) {
  const geometry = useMemo(() => buildScatterGeometry(controller.plotRows), [controller.plotRows]);
  const [localHover, setLocalHover] = useState<string | null>(null);
  const hoveredCode = localHover ?? controller.hoveredSectorCode;
  const hovered = controller.plotRows.find((row) => row.sectorCode === hoveredCode) ?? null;
  const stateFilter = controller.urlState?.stateFilter ?? "all";
  return (
    <section className="price-volume-scatter-card">
      <header><strong>区间涨跌幅 × 成交活跃度</strong><span>零轴固定 · 所有真实点完整呈现</span></header>
      <div className="price-volume-scatter-wrap">
        <svg aria-label="行业区间涨跌幅与成交活跃度二维分布" role="img" viewBox={`0 0 ${geometry.width} ${geometry.height}`}>
          <title>行业区间涨跌幅与成交活跃度二维分布</title>
          <desc>横轴为区间涨跌幅，纵轴为成交活跃度。点击圆点选择行业。</desc>
          {[0, .25, .5, .75, 1].map((ratio) => <line className="grid-line" key={`h-${ratio}`} x1={geometry.left} x2={geometry.right} y1={geometry.top + ratio * (geometry.bottom - geometry.top)} y2={geometry.top + ratio * (geometry.bottom - geometry.top)} />)}
          {[0, .25, .5, .75, 1].map((ratio) => <line className="grid-line" key={`v-${ratio}`} x1={geometry.left + ratio * (geometry.right - geometry.left)} x2={geometry.left + ratio * (geometry.right - geometry.left)} y1={geometry.top} y2={geometry.bottom} />)}
          <line className="zero-line" x1={geometry.zeroX} x2={geometry.zeroX} y1={geometry.top} y2={geometry.bottom} /><line className="zero-line" x1={geometry.left} x2={geometry.right} y1={geometry.zeroY} y2={geometry.zeroY} />
          <text className="quadrant amount" x={geometry.left + 12} y={geometry.top + 18}>成交增强、价格未增强</text><text className="quadrant joint" textAnchor="end" x={geometry.right - 12} y={geometry.top + 18}>量价共同增强</text><text className="quadrant neutral" x={geometry.left + 12} y={geometry.bottom - 10}>量价均不明显</text><text className="quadrant price" textAnchor="end" x={geometry.right - 12} y={geometry.bottom - 10}>价格增强、成交未增强</text>
          {axisTicks(geometry.xDomain.min, geometry.xDomain.max).map((tick, index) => <text className="axis-label" key={`x-${tick}`} textAnchor="middle" x={geometry.left + index * (geometry.right - geometry.left) / 4} y={geometry.height - 8}>{formatTick(tick)}</text>)}
          {axisTicks(geometry.yDomain.max, geometry.yDomain.min).map((tick, index) => <text className="axis-label" key={`y-${tick}`} x={2} y={geometry.top + index * (geometry.bottom - geometry.top) / 4 + 3}>{formatTick(tick)}</text>)}
          <text className="axis-title" textAnchor="middle" x={(geometry.left + geometry.right) / 2} y={geometry.height - 20}>区间涨跌幅</text><text className="axis-title" x={2} y={14}>成交活跃度</text>
          {geometry.points.map((point) => {
            const row = controller.plotRows.find((item) => item.sectorCode === point.sectorCode)!;
            const selected = controller.selectedRow?.sectorCode === row.sectorCode;
            const highlighted = matchesFilter(row.state, stateFilter);
            return <g key={row.sectorCode}><circle aria-label={`${row.sectorName}，区间涨跌幅${row.priceText}，成交活跃度${row.amountText}`} className={`price-volume-point ${row.stateClass} ${selected ? "selected" : ""} ${highlighted ? "" : "dimmed"}`} cx={point.x} cy={point.y} r={selected ? 7 : 5} role="button" tabIndex={0} onBlur={() => { setLocalHover(null); controller.setHoveredSector(null); }} onClick={() => controller.selectSector(row.sectorCode)} onFocus={() => { setLocalHover(row.sectorCode); controller.setHoveredSector(row.sectorCode); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") controller.selectSector(row.sectorCode); }} onMouseEnter={() => setLocalHover(row.sectorCode)} onMouseLeave={() => setLocalHover(null)} />{selected ? <text className="selected-label" textAnchor={point.x > geometry.width * .72 ? "end" : "start"} x={point.x + (point.x > geometry.width * .72 ? -10 : 10)} y={point.y - 10}>{row.sectorName}</text> : null}</g>;
          })}
        </svg>
        {hovered ? <div className="price-volume-scatter-tooltip" role="tooltip"><strong>{hovered.sectorName}</strong><span title={hovered.hierarchyPath}>{hovered.hierarchyPath}</span><span>区间涨跌幅 <b className="num">{hovered.priceText}</b></span><span>成交活跃度 <b className="num amount-value">{hovered.amountText}</b></span><span>{hovered.stateText}</span></div> : null}
      </div>
    </section>
  );
}

function axisTicks(start: number, end: number) { return Array.from({ length: 5 }, (_, index) => start + (end - start) * index / 4); }
function formatTick(value: number) { const rounded = Math.abs(value) >= 100 ? value.toFixed(0) : value.toFixed(1); return `${value > 0 ? "+" : ""}${rounded}%`; }
function matchesFilter(state: string | null, filter: string) { if (filter === "all") return true; if (filter === "joint") return state === "JOINT"; if (filter === "price") return state === "PRICE_ONLY"; if (filter === "amount") return state === "AMOUNT_ONLY"; return state === "NEUTRAL"; }
