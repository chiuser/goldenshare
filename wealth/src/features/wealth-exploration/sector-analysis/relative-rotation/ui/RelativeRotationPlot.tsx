import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import {
  buildTrailSegments,
  chooseLabelPosition,
  RELATIVE_ROTATION_PLOT,
  RELATIVE_ROTATION_VIEWBOX,
  toRelativeRotationPixels,
  type RelativeRotationPixelPoint,
  type RelativeRotationPlotScale,
} from "../model/relativeRotationPlotGeometry";
import type { SectorRelativeRotationController } from "../model/useSectorRelativeRotationController";
import type { SectorRelativeRotationRowViewModel } from "../model/sectorRelativeRotationTypes";
import { RelativeRotationSelectedSummary } from "./RelativeRotationSelectedSummary";

export function RelativeRotationPlot({ controller }: { controller: SectorRelativeRotationController }) {
  const [expanded, setExpanded] = useState(false);
  const expandButtonRef = useRef<HTMLButtonElement>(null);
  const closeExpanded = useCallback(() => setExpanded(false), []);
  const { viewState } = controller;
  if (viewState.kind !== "ready" && viewState.kind !== "delayed") return null;
  const analysis = viewState.results.analysis;
  return (
    <>
      <section className="relative-plot-card">
        <header className="relative-plot-header">
          <div><strong>{analysis.scopeTitle}</strong><span>横轴：同组强度百分位　纵轴：5日强度变化</span></div>
          <div className="relative-plot-actions"><span>{analysis.groupInterpretation === "SAMPLE_INSUFFICIENT" ? "样本不足，仅展示客观位置" : `${analysis.plottableCount} 个行业可绘制`}</span><button aria-label="放大相对轮动图" ref={expandButtonRef} type="button" onClick={() => setExpanded(true)}>放大</button></div>
        </header>
        <RelativeRotationSelectedSummary controller={controller} />
        <RelativeRotationSvg controller={controller} scale={controller.plotScale} />
        {controller.selectedRow?.coordinateStatus === "UNAVAILABLE" ? <div className="relative-missing-coordinate" role="status">当前行业坐标不可计算，已保留可用事实与历史日期槽</div> : null}
      </section>
      {expanded ? <RelativeRotationExpandedDialog controller={controller} scale={controller.plotScale} triggerRef={expandButtonRef} onClose={closeExpanded} /> : null}
    </>
  );
}

function RelativeRotationExpandedDialog({ controller, scale, triggerRef, onClose }: { controller: SectorRelativeRotationController; scale: RelativeRotationPlotScale; triggerRef: React.RefObject<HTMLButtonElement | null>; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const close = useCallback(() => {
    onClose();
    window.setTimeout(() => triggerRef.current?.focus(), 0);
  }, [onClose, triggerRef]);
  useEffect(() => {
    closeRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") close(); };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [close]);
  return (
    <div className="relative-plot-dialog-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
      <section aria-label="放大的行业相对轮动图" aria-modal="true" className="relative-plot-dialog" role="dialog">
        <header><strong>行业相对轮动</strong><button aria-label="关闭放大图" ref={closeRef} type="button" onClick={close}>关闭</button></header>
        <RelativeRotationSvg controller={controller} scale={scale} />
      </section>
    </div>
  );
}

function RelativeRotationSvg({ controller, scale }: { controller: SectorRelativeRotationController; scale: RelativeRotationPlotScale }) {
  const viewState = controller.viewState;
  if (viewState.kind !== "ready" && viewState.kind !== "delayed") return null;
  const analysis = viewState.results.analysis;
  const selectedCode = analysis.selectedSectorCode;
  const points = useMemo(() => controller.plotRows.map((row) => ({ row, ...toRelativeRotationPixels(row.percentile!, row.percentileDelta5d!, scale) })), [controller.plotRows, scale]);
  const selected = points.find((point) => point.row.sectorCode === selectedCode) ?? null;
  const hovered = points.find((point) => point.row.sectorCode === controller.hoveredCode) ?? null;
  const trailSegments = useMemo(() => buildTrailSegments(analysis.selectedTrail.points, scale), [analysis.selectedTrail.points, scale]);
  const trailPoints = analysis.selectedTrail.points.filter((point) => point.coordinateStatus === "PLOTTABLE" && point.percentile !== null && point.percentileDelta5d !== null).map((point) => ({ point, ...toRelativeRotationPixels(point.percentile!, point.percentileDelta5d!, scale) }));
  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;
    const x = (event.clientX - rect.left) * RELATIVE_ROTATION_VIEWBOX.width / rect.width;
    const y = (event.clientY - rect.top) * RELATIVE_ROTATION_VIEWBOX.height / rect.height;
    const radius = 10 * RELATIVE_ROTATION_VIEWBOX.width / rect.width;
    const hit = points.map((point) => ({ point, distance: Math.hypot(point.x - x, point.y - y) }))
      .filter((candidate) => candidate.distance <= radius)
      .sort((left, right) => Number(right.point.row.sectorCode === selectedCode) - Number(left.point.row.sectorCode === selectedCode) || left.distance - right.distance || left.point.row.sectorCode.localeCompare(right.point.row.sectorCode))[0];
    controller.setHoveredSector(hit?.point.row.sectorCode ?? null);
  };
  return (
    <svg aria-label="行业相对轮动四象限图" className="relative-rotation-svg" role="img" viewBox={`0 0 ${RELATIVE_ROTATION_VIEWBOX.width} ${RELATIVE_ROTATION_VIEWBOX.height}`} onPointerLeave={() => controller.setHoveredSector(null)} onPointerMove={handlePointerMove}>
      <QuadrantBackground scale={scale} />
      {scale.yTicks.map((tick) => { const pixel = toRelativeRotationPixels(0, tick, scale); return <g key={`y-${tick}`}><line className={tick === 0 ? "relative-zero-line" : "relative-chart-grid"} x1={RELATIVE_ROTATION_PLOT.left} x2={RELATIVE_ROTATION_VIEWBOX.width - RELATIVE_ROTATION_PLOT.right} y1={pixel.y} y2={pixel.y} /><text className="relative-axis-label" textAnchor="end" x={RELATIVE_ROTATION_PLOT.left - 9} y={pixel.y + 4}>{formatTick(tick)}</text></g>; })}
      {scale.xTicks.map((tick) => { const pixel = toRelativeRotationPixels(tick, 0, scale); return <g key={`x-${tick}`}><line className={tick === 50 ? "relative-zero-line" : "relative-chart-grid"} x1={pixel.x} x2={pixel.x} y1={RELATIVE_ROTATION_PLOT.top} y2={RELATIVE_ROTATION_VIEWBOX.height - RELATIVE_ROTATION_PLOT.bottom} /><text className="relative-axis-label" textAnchor="middle" x={pixel.x} y={RELATIVE_ROTATION_VIEWBOX.height - 28}>{tick}%</text></g>; })}
      <text className="relative-axis-title" textAnchor="middle" x={RELATIVE_ROTATION_VIEWBOX.width / 2} y={RELATIVE_ROTATION_VIEWBOX.height - 8}>同组强度百分位</text>
      <text className="relative-axis-title" x={RELATIVE_ROTATION_PLOT.left} y={20}>5日强度变化（百分点）</text>
      {points.filter((point) => point.row.sectorCode !== selectedCode).map((point) => <RotationPoint controller={controller} key={point.row.sectorCode} point={point} selected={false} />)}
      {trailSegments.map((segment, index) => <polyline className="relative-selected-trail" fill="none" key={index} points={segment.map((point) => `${point.x},${point.y}`).join(" ")} />)}
      {trailPoints.map((point) => <circle className="relative-trail-point" cx={point.x} cy={point.y} key={point.point.tradeDate} r="3" />)}
      {selected ? <RotationPoint controller={controller} point={selected} selected /> : null}
      {selected ? <SelectedLabel point={selected} avoidBelow={hovered?.row.sectorCode === selected.row.sectorCode} /> : null}
      {hovered ? <HoverTooltip point={hovered} /> : null}
    </svg>
  );
}

function QuadrantBackground({ scale }: { scale: RelativeRotationPlotScale }) {
  const split = toRelativeRotationPixels(50, 0, scale);
  const right = RELATIVE_ROTATION_VIEWBOX.width - RELATIVE_ROTATION_PLOT.right;
  const bottom = RELATIVE_ROTATION_VIEWBOX.height - RELATIVE_ROTATION_PLOT.bottom;
  return <g className="relative-quadrants"><rect className="weak-improving" x={RELATIVE_ROTATION_PLOT.left} y={RELATIVE_ROTATION_PLOT.top} width={split.x - RELATIVE_ROTATION_PLOT.left} height={split.y - RELATIVE_ROTATION_PLOT.top} /><rect className="leading-improving" x={split.x} y={RELATIVE_ROTATION_PLOT.top} width={right - split.x} height={split.y - RELATIVE_ROTATION_PLOT.top} /><rect className="weak-not-improving" x={RELATIVE_ROTATION_PLOT.left} y={split.y} width={split.x - RELATIVE_ROTATION_PLOT.left} height={bottom - split.y} /><rect className="strong-not-improving" x={split.x} y={split.y} width={right - split.x} height={bottom - split.y} /><text x={RELATIVE_ROTATION_PLOT.left + 12} y={RELATIVE_ROTATION_PLOT.top + 20}>偏弱但改善</text><text textAnchor="end" x={right - 12} y={RELATIVE_ROTATION_PLOT.top + 20}>领先且改善</text><text x={RELATIVE_ROTATION_PLOT.left + 12} y={bottom - 12}>偏弱且未改善</text><text textAnchor="end" x={right - 12} y={bottom - 12}>强势但未改善</text></g>;
}

function RotationPoint({ controller, point, selected }: { controller: SectorRelativeRotationController; point: RelativeRotationPixelPoint & { row: SectorRelativeRotationRowViewModel }; selected: boolean }) {
  return <circle aria-label={`${point.row.sectorName}，强度${point.row.percentileText}，5日变化${point.row.deltaText}`} className={`relative-rotation-point ${point.row.statusClass} ${selected ? "selected" : ""}`} cx={point.x} cy={point.y} r={selected ? 7 : 4.5} role="button" tabIndex={0} onBlur={() => controller.setHoveredSector(null)} onClick={() => controller.selectSector(point.row.sectorCode)} onFocus={() => controller.setHoveredSector(point.row.sectorCode)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); controller.selectSector(point.row.sectorCode); } }} />;
}

function SelectedLabel({ point, avoidBelow }: { point: RelativeRotationPixelPoint & { row: SectorRelativeRotationRowViewModel }; avoidBelow: boolean }) {
  const textRef = useRef<SVGTextElement>(null);
  const [label, setLabel] = useState(point.row.sectorName);
  const [width, setWidth] = useState(96);
  useLayoutEffect(() => {
    const element = textRef.current;
    if (!element) return;
    const measure = () => typeof element.getComputedTextLength === "function" ? element.getComputedTextLength() : (element.textContent ?? "").length * 12;
    let next = point.row.sectorName;
    element.textContent = next;
    while (measure() > 196 && [...next].length > 2) {
      next = `${[...next].slice(0, -2).join("")}…`;
      element.textContent = next;
    }
    setLabel(next);
    setWidth(Math.min(220, Math.max(64, measure() + 24)));
  }, [point.row.sectorName]);
  const position = chooseLabelPosition(point, width, 28, avoidBelow);
  return <g className="relative-selected-label" transform={`translate(${position.x} ${position.y})`}><title>{point.row.sectorName}</title><rect height="28" rx="6" width={width} /><text ref={textRef} textAnchor="middle" x={width / 2} y="18">{label}</text></g>;
}

function HoverTooltip({ point }: { point: RelativeRotationPixelPoint & { row: SectorRelativeRotationRowViewModel } }) {
  const width = 218;
  const height = 100;
  const position = chooseLabelPosition(point, width, height, false);
  return <g className="relative-plot-tooltip" pointerEvents="none" transform={`translate(${position.x} ${position.y})`}><rect height={height} rx="7" width={width} /><text className="title" x="12" y="21">{point.row.sectorName}</text><text x="12" y="41">{point.row.hierarchyPath}</text><text x="12" y="61">强度 {point.row.percentileText}　变化 {point.row.deltaText}</text><text x="12" y="81">区间涨跌幅 {point.row.returnText}</text></g>;
}

function formatTick(value: number) { const normalized = Math.abs(value) < 0.0001 ? 0 : value; return `${normalized > 0 ? "+" : ""}${Number(normalized.toFixed(1))}`; }
