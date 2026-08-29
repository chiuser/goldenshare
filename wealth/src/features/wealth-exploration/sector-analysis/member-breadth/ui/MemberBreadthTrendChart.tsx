import type { CSSProperties } from "react";

import type { SectorMemberBreadthDetailsViewModel } from "../model/sectorMemberBreadthTypes";

const VIEW = { width: 920, height: 244, left: 48, right: 18, top: 22, bottom: 30 } as const;
const SERIES = [
  { key: "memberPct", label: "成分股占比", cls: "member" },
  { key: "turnoverPct", label: "成交额占比", cls: "turnover" },
  { key: "maPositionPct", label: "均线位置占比", cls: "ma" },
] as const;

export type MemberBreadthTrendInspection = null | {
  index: number;
  pointerY: number;
};

export function MemberBreadthTrendChart({ details, inspection, onInspectionChange }: { details: SectorMemberBreadthDetailsViewModel; inspection: MemberBreadthTrendInspection; onInspectionChange: (inspection: MemberBreadthTrendInspection) => void }) {
  const points = details.trend;
  const plotWidth = VIEW.width - VIEW.left - VIEW.right;
  const plotHeight = VIEW.height - VIEW.top - VIEW.bottom;
  const x = (index: number) => VIEW.left + (points.length <= 1 ? plotWidth / 2 : index / (points.length - 1) * plotWidth);
  const y = (value: number) => VIEW.top + (100 - value) / 100 * plotHeight;

  const updateInspection = (event: { currentTarget: SVGSVGElement; clientX: number; clientY: number }, activeOnly: boolean) => {
    const mapped = mapPointerToViewBox(event.currentTarget, event.clientX, event.clientY);
    if (!mapped || !isInsidePlot(mapped.x, mapped.y) || points.length === 0) {
      if (!activeOnly) onInspectionChange(null);
      return;
    }
    const next = {
      index: nearestPointIndex(mapped.x, points.length, plotWidth),
      pointerY: clamp(mapped.y, VIEW.top, VIEW.top + plotHeight),
    };
    if (!activeOnly || inspection !== null) onInspectionChange(next);
  };

  const activePoint = inspection === null ? null : points[inspection.index] ?? null;
  const activeX = inspection === null ? null : x(inspection.index);
  const xLabelCenter = activeX === null ? null : clamp(activeX, 28, VIEW.width - 28);
  const yLabelCenter = inspection === null ? null : clamp(inspection.pointerY, VIEW.top + 9, VIEW.top + plotHeight - 9);
  const pointerPct = inspection === null ? null : 100 - (inspection.pointerY - VIEW.top) / plotHeight * 100;
  const tooltipSide = activeX !== null && (activeX - VIEW.left) / plotWidth > 0.62 ? "left" : "right";
  const tooltipStyle = activeX === null ? undefined : ({ "--member-breadth-inspection-x": `${activeX / VIEW.width * 100}%` } as CSSProperties);

  return (
    <section className="member-breadth-trend-card">
      <header>
        <div><strong>{details.historyRange}日成员广度趋势</strong><span>三项事实共用 0–100% 纵轴</span></div>
        <div className="member-breadth-trend-legend">{SERIES.map((series) => <span key={series.key}><i className={series.cls} />{series.label}</span>)}</div>
      </header>
      <div className="member-breadth-trend-body">
        <svg
          aria-label={`${details.sectorName}${details.historyRange}日成员广度趋势，单击绘图区查看具体日期`}
          className="member-breadth-trend-svg"
          preserveAspectRatio="none"
          role="img"
          tabIndex={0}
          viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
          onClick={(event) => {
            event.currentTarget.focus();
            updateInspection(event, false);
          }}
          onKeyDown={(event) => {
            if (event.key !== "Escape") return;
            event.preventDefault();
            onInspectionChange(null);
          }}
          onPointerMove={(event) => updateInspection(event, true)}
        >
          <title>{details.sectorName}{details.historyRange}日成员广度趋势</title>
          <desc>单击绘图区后查看最近交易日的三项广度值，鼠标离开后保留读数，按 Escape 或单击坐标轴区域退出。</desc>
          {[0, 25, 50, 75, 100].map((tick) => <g key={tick}><line className="member-breadth-grid-line" x1={VIEW.left} x2={VIEW.width - VIEW.right} y1={y(tick)} y2={y(tick)} /><text className="member-breadth-axis-label" textAnchor="end" x={VIEW.left - 8} y={y(tick) + 4}>{tick}%</text></g>)}
          {SERIES.map((series) => buildSegments(points.map((point) => point[series.key]), x, y).map((path, index) => <path className={`member-breadth-trend-line ${series.cls}`} d={path} fill="none" key={`${series.key}-${index}`} />))}
          {points.map((point, index) => index % Math.max(1, Math.ceil(points.length / 5)) === 0 || index === points.length - 1 ? <text className="member-breadth-axis-label" key={point.tradeDate} textAnchor={index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"} x={x(index)} y={VIEW.height - 8}>{point.tradeDate.slice(5)}</text> : null)}
          {inspection !== null && activePoint && activeX !== null && xLabelCenter !== null && yLabelCenter !== null && pointerPct !== null ? (
            <g className="member-breadth-inspection-layer" aria-hidden="true">
              <line className="member-breadth-inspection-crosshair" x1={activeX} x2={activeX} y1={VIEW.top} y2={VIEW.top + plotHeight} />
              <line className="member-breadth-inspection-crosshair" x1={VIEW.left} x2={VIEW.width - VIEW.right} y1={inspection.pointerY} y2={inspection.pointerY} />
              {SERIES.map((series) => {
                const value = activePoint[series.key];
                return value === null ? null : <circle className={`member-breadth-inspection-point ${series.cls}`} cx={activeX} cy={y(value)} key={series.key} r="4.5" />;
              })}
              <g className="member-breadth-inspection-axis-pill">
                <rect height="18" rx="4" width="54" x={xLabelCenter - 27} y={VIEW.height - 25} />
                <text textAnchor="middle" x={xLabelCenter} y={VIEW.height - 12}>{activePoint.tradeDate.slice(5)}</text>
              </g>
              <g className="member-breadth-inspection-axis-pill">
                <rect height="18" rx="4" width="44" x="1" y={yLabelCenter - 9} />
                <text textAnchor="middle" x="23" y={yLabelCenter + 3.5}>{pointerPct.toFixed(1)}%</text>
              </g>
            </g>
          ) : null}
        </svg>
        {inspection !== null && activePoint ? (
          <div className={`member-breadth-trend-tooltip ${tooltipSide}`} role="tooltip" style={tooltipStyle}>
            <strong>{activePoint.tradeDate}</strong>
            {SERIES.map((series) => <span key={series.key}><i className={series.cls} />{series.label}<b>{formatPercent(activePoint[series.key])}</b></span>)}
          </div>
        ) : null}
      </div>
    </section>
  );
}

function mapPointerToViewBox(svg: SVGSVGElement, clientX: number, clientY: number): { x: number; y: number } | null {
  const bounds = svg.getBoundingClientRect();
  if (bounds.width <= 0 || bounds.height <= 0) return null;
  return {
    x: (clientX - bounds.left) / bounds.width * VIEW.width,
    y: (clientY - bounds.top) / bounds.height * VIEW.height,
  };
}

function isInsidePlot(x: number, y: number): boolean {
  return x >= VIEW.left && x <= VIEW.width - VIEW.right && y >= VIEW.top && y <= VIEW.height - VIEW.bottom;
}

function nearestPointIndex(viewX: number, pointCount: number, plotWidth: number): number {
  if (pointCount <= 1) return 0;
  return clamp(Math.round((viewX - VIEW.left) / plotWidth * (pointCount - 1)), 0, pointCount - 1);
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(maximum, Math.max(minimum, value));
}

function formatPercent(value: number | null): string {
  return value === null ? "--" : `${value.toFixed(1)}%`;
}

function buildSegments(values: Array<number | null>, x: (index: number) => number, y: (value: number) => number): string[] {
  const segments: string[] = [];
  let current = "";
  values.forEach((value, index) => {
    if (value === null) {
      if (current) segments.push(current);
      current = "";
      return;
    }
    current += `${current ? " L" : "M"}${x(index).toFixed(2)} ${y(value).toFixed(2)}`;
  });
  if (current) segments.push(current);
  return segments;
}
