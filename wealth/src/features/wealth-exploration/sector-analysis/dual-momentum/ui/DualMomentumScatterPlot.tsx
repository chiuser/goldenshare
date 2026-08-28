import { useEffect, useMemo, useRef, useState } from "react";

import type { SectorDualMomentumController } from "../model/useSectorDualMomentumController";
import type { SectorDualMomentumRowViewModel } from "../model/sectorDualMomentumTypes";

const VIEWBOX_WIDTH = 776;
const VIEWBOX_HEIGHT = 658;
const PLOT = { left: 72, right: 36, top: 26, bottom: 64 };

export function DualMomentumScatterPlot({ controller }: { controller: SectorDualMomentumController }) {
  const [expanded, setExpanded] = useState(false);
  const expandButtonRef = useRef<HTMLButtonElement>(null);
  const { viewState, urlState } = controller;
  if ((viewState.kind !== "ready" && viewState.kind !== "delayed") || !urlState) return null;
  const analysis = viewState.results.analysis;
  return (
    <>
      <section className="dual-scatter-card">
        <header>
          <div><strong>行业双动量分布</strong><span>横轴：{urlState.period}日区间涨跌幅　纵轴：同组强度百分位</span></div>
          <div className="dual-scatter-actions">
            <span>{analysis.plottableCount} 可绘制 · {analysis.totalCount - analysis.plottableCount} 仅列表</span>
            <button aria-label="放大双动量分布图" ref={expandButtonRef} type="button" onClick={() => setExpanded(true)}>放大</button>
          </div>
        </header>
        <ScatterSvg controller={controller} />
        {controller.selectedRow?.coordinateStatus === "UNAVAILABLE" ? <div className="dual-missing-coordinate" role="status">当前行业坐标不可计算</div> : null}
      </section>
      {expanded ? (
        <ScatterDialog controller={controller} onClose={() => { setExpanded(false); window.setTimeout(() => expandButtonRef.current?.focus(), 0); }} />
      ) : null}
    </>
  );
}

function ScatterDialog({ controller, onClose }: { controller: SectorDualMomentumController; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);
  return (
    <div className="dual-scatter-dialog-backdrop" role="presentation">
      <section aria-label="放大的行业双动量分布图" aria-modal="true" className="dual-scatter-dialog" role="dialog">
        <header><strong>行业双动量分布</strong><button aria-label="关闭放大图" ref={closeRef} type="button" onClick={onClose}>关闭</button></header>
        <ScatterSvg controller={controller} />
      </section>
    </div>
  );
}

function ScatterSvg({ controller }: { controller: SectorDualMomentumController }) {
  const [hoveredCode, setHoveredCode] = useState<string | null>(null);
  const rows = controller.plotRows;
  const threshold = controller.urlState?.threshold ?? 80;
  const selectedCode = controller.viewState.kind === "ready" || controller.viewState.kind === "delayed"
    ? controller.viewState.selectedCode
    : null;
  const geometry = useMemo(() => buildGeometry(rows, threshold), [rows, threshold]);
  const hovered = rows.find((row) => row.sectorCode === hoveredCode) ?? null;
  const selected = rows.find((row) => row.sectorCode === selectedCode) ?? null;
  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const x = (event.clientX - rect.left) * VIEWBOX_WIDTH / rect.width;
    const y = (event.clientY - rect.top) * VIEWBOX_HEIGHT / rect.height;
    const radius = 10 * VIEWBOX_WIDTH / rect.width;
    const candidates = geometry.points
      .map((point) => ({ point, distance: Math.hypot(point.x - x, point.y - y) }))
      .filter((candidate) => candidate.distance <= radius)
      .sort((left, right) => left.distance - right.distance
        || Number(right.point.row.sectorCode === selectedCode) - Number(left.point.row.sectorCode === selectedCode)
        || left.point.row.sectorCode.localeCompare(right.point.row.sectorCode));
    setHoveredCode(candidates[0]?.point.row.sectorCode ?? null);
  };
  return (
    <svg
      aria-label="行业双动量二维分布图"
      className="dual-scatter-svg"
      role="img"
      tabIndex={0}
      viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
      onPointerLeave={() => setHoveredCode(null)}
      onPointerMove={handlePointerMove}
    >
      <rect className="dual-qualified-zone" x={geometry.zeroX} y={geometry.y(threshold)} width={geometry.right - geometry.zeroX} height={geometry.bottom - geometry.y(threshold)} />
      {[0, 20, 40, 60, 80, 100].map((tick) => <g key={`y-${tick}`}><line className="dual-chart-grid" x1={geometry.left} x2={geometry.right} y1={geometry.y(tick)} y2={geometry.y(tick)} /><text className="dual-chart-label" textAnchor="end" x={geometry.left - 8} y={geometry.y(tick) + 4}>{tick}%</text></g>)}
      {geometry.xTicks.map((tick) => <g key={`x-${tick}`}><line className="dual-chart-grid" x1={geometry.x(tick)} x2={geometry.x(tick)} y1={geometry.top} y2={geometry.bottom} /><text className="dual-chart-label" textAnchor="middle" x={geometry.x(tick)} y={geometry.bottom + 22}>{formatAxis(tick)}%</text></g>)}
      <line className="dual-chart-threshold" x1={geometry.zeroX} x2={geometry.zeroX} y1={geometry.top} y2={geometry.bottom} />
      <line className="dual-chart-threshold" x1={geometry.left} x2={geometry.right} y1={geometry.y(threshold)} y2={geometry.y(threshold)} />
      <text className="dual-chart-axis-title" textAnchor="middle" x={(geometry.left + geometry.right) / 2} y={VIEWBOX_HEIGHT - 12}>所选周期区间涨跌幅</text>
      <text className="dual-chart-axis-title" x={geometry.left} y={16}>同组强度百分位</text>
      {geometry.points.map((point) => (
        <circle
          aria-label={`${point.row.sectorName}，区间涨跌幅${point.row.returnText}，强度百分位${point.row.percentileText}`}
          className={`dual-scatter-point ${pointClass(point.row)} ${point.row.sectorCode === selectedCode ? "selected" : ""}`}
          cx={point.x}
          cy={point.y}
          key={point.row.sectorCode}
          r={point.row.sectorCode === selectedCode ? 7 : 4.5}
          role="button"
          tabIndex={0}
          onClick={() => controller.selectSector(point.row.sectorCode)}
          onFocus={() => setHoveredCode(point.row.sectorCode)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              controller.selectSector(point.row.sectorCode);
            }
          }}
        />
      ))}
      {selected ? <SelectedLabel row={selected} x={geometry.x(selected.returnPct!)} y={geometry.y(selected.percentile!)} /> : null}
      {hovered ? <HoverTooltip row={hovered} x={geometry.x(hovered.returnPct!)} y={geometry.y(hovered.percentile!)} /> : null}
    </svg>
  );
}

function SelectedLabel({ row, x, y }: { row: SectorDualMomentumRowViewModel; x: number; y: number }) {
  const labelX = Math.min(Math.max(x + 8, 80), 640);
  const labelY = Math.min(Math.max(y - 32, 8), 610);
  return <g className="dual-selected-point-label" transform={`translate(${labelX} ${labelY})`}><rect height="24" rx="5" width="124" /><text x="8" y="16">{row.sectorName}　{row.returnText}</text></g>;
}

function HoverTooltip({ row, x, y }: { row: SectorDualMomentumRowViewModel; x: number; y: number }) {
  const tooltipX = Math.min(Math.max(x + 12, 80), 556);
  const tooltipY = Math.min(Math.max(y + 12, 72), 540);
  return (
    <g className="dual-scatter-tooltip" pointerEvents="none" transform={`translate(${tooltipX} ${tooltipY})`}>
      <rect height="92" rx="7" width="196" />
      <text className="title" x="10" y="20">{row.sectorName}</text>
      <text x="10" y="38">{row.hierarchyPath}</text>
      <text x="10" y="56">涨跌幅 {row.returnText}</text>
      <text x="10" y="73">排名 {row.rankText}　百分位 {row.percentileText}</text>
    </g>
  );
}

function buildGeometry(rows: SectorDualMomentumRowViewModel[], threshold: number) {
  const left = PLOT.left;
  const right = VIEWBOX_WIDTH - PLOT.right;
  const top = PLOT.top;
  const bottom = VIEWBOX_HEIGHT - PLOT.bottom;
  const values = rows.map((row) => Math.abs(row.returnPct ?? 0));
  const maximum = Math.max(0, ...values);
  const extent = maximum === 0 ? 1 : maximum * 1.08;
  const x = (value: number) => left + ((value + extent) / (extent * 2)) * (right - left);
  const y = (value: number) => bottom - (value / 100) * (bottom - top);
  const xTicks = [-extent, -extent / 2, 0, extent / 2, extent];
  return { left, right, top, bottom, x, y, xTicks, zeroX: x(0), threshold, points: rows.map((row) => ({ row, x: x(row.returnPct!), y: y(row.percentile!) })) };
}

function pointClass(row: SectorDualMomentumRowViewModel) {
  if (row.displayStatus === "SAMPLE_INSUFFICIENT") return "sample-insufficient";
  return row.statusClass;
}

function formatAxis(value: number) {
  const normalized = Math.abs(value) < 0.005 ? 0 : value;
  return `${normalized > 0 ? "+" : ""}${normalized.toFixed(1)}`;
}
