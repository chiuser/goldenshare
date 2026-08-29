import type { SectorMemberBreadthDetailsViewModel } from "../model/sectorMemberBreadthTypes";

const VIEW = { width: 920, height: 244, left: 48, right: 18, top: 22, bottom: 30 } as const;
const SERIES = [
  { key: "memberPct", label: "成分股占比", cls: "member" },
  { key: "turnoverPct", label: "成交额占比", cls: "turnover" },
  { key: "maPositionPct", label: "均线位置占比", cls: "ma" },
] as const;

export function MemberBreadthTrendChart({ details }: { details: SectorMemberBreadthDetailsViewModel }) {
  const points = details.trend; const plotWidth = VIEW.width - VIEW.left - VIEW.right; const plotHeight = VIEW.height - VIEW.top - VIEW.bottom;
  const x = (index: number) => VIEW.left + (points.length <= 1 ? plotWidth / 2 : index / (points.length - 1) * plotWidth); const y = (value: number) => VIEW.top + (100 - value) / 100 * plotHeight;
  return <section className="member-breadth-trend-card"><header><div><strong>{details.historyRange}日成员广度趋势</strong><span>三项事实共用 0–100% 纵轴</span></div><div className="member-breadth-trend-legend">{SERIES.map((series) => <span key={series.key}><i className={series.cls} />{series.label}</span>)}</div></header>
    <svg aria-label={`${details.sectorName}${details.historyRange}日成员广度趋势`} className="member-breadth-trend-svg" role="img" viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}>
      {[0, 25, 50, 75, 100].map((tick) => <g key={tick}><line className="member-breadth-grid-line" x1={VIEW.left} x2={VIEW.width - VIEW.right} y1={y(tick)} y2={y(tick)} /><text className="member-breadth-axis-label" textAnchor="end" x={VIEW.left - 8} y={y(tick) + 4}>{tick}%</text></g>)}
      {SERIES.map((series) => buildSegments(points.map((point) => point[series.key]), x, y).map((path, index) => <path className={`member-breadth-trend-line ${series.cls}`} d={path} fill="none" key={`${series.key}-${index}`} />))}
      {points.map((point, index) => index % Math.max(1, Math.ceil(points.length / 5)) === 0 || index === points.length - 1 ? <text className="member-breadth-axis-label" key={point.tradeDate} textAnchor={index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"} x={x(index)} y={VIEW.height - 8}>{point.tradeDate.slice(5)}</text> : null)}
    </svg>
  </section>;
}
function buildSegments(values: Array<number | null>, x: (index: number) => number, y: (value: number) => number): string[] { const segments: string[] = []; let current = ""; values.forEach((value, index) => { if (value === null) { if (current) segments.push(current); current = ""; return; } current += `${current ? " L" : "M"}${x(index).toFixed(2)} ${y(value).toFixed(2)}`; }); if (current) segments.push(current); return segments; }
