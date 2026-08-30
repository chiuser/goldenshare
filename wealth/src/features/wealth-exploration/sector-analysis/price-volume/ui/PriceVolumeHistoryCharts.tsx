import { useMemo, useState } from "react";

import { buildHistorySegments, clientPointToViewBox } from "../model/sectorPriceVolumeGeometry";
import type { SectorPriceVolumeController } from "../model/useSectorPriceVolumeController";
import type { PriceVolumeHistoryPointViewModel } from "../api/sectorPriceVolumeTypes";

export function PriceVolumeHistoryCharts({ controller }: { controller: SectorPriceVolumeController }) {
  const state = controller.detailsState;
  if (state.kind === "idle" || state.kind === "loading") return <HistoryShell controller={controller}><div className="price-volume-history-local-state" role="status">历史变化正在加载</div></HistoryShell>;
  if (state.kind === "error") return <HistoryShell controller={controller}><div className="price-volume-history-local-state" role="alert"><strong>历史变化加载失败</strong><span>{state.message}</span>{state.retryable ? <button type="button" onClick={controller.retryDetails}>重试</button> : null}</div></HistoryShell>;
  if (state.kind === "empty") return <HistoryShell controller={controller}><div className="price-volume-history-local-state" role="status"><strong>暂无历史变化</strong><span>{state.message}</span></div></HistoryShell>;
  return <HistoryShell controller={controller}><HistoryPlots points={state.data.history} period={state.data.period} /></HistoryShell>;
}

function HistoryShell({ controller, children }: { controller: SectorPriceVolumeController; children: React.ReactNode }) {
  return <section className="price-volume-history-card"><header><div><strong>历史变化</strong><span>滚动 {controller.urlState?.period ?? 20} 日 · 共享日期轴</span></div><div className="price-volume-history-ranges" aria-label="历史显示范围">{([20, 30, 60] as const).map((range) => <button aria-pressed={controller.urlState?.historyRange === range} className={controller.urlState?.historyRange === range ? "active" : ""} key={range} type="button" onClick={() => controller.selectHistoryRange(range)}>{range}日</button>)}</div></header>{children}</section>;
}

function HistoryPlots({ points, period }: { points: PriceVolumeHistoryPointViewModel[]; period: number }) {
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const price = useMemo(() => buildHistorySegments(points, "priceMomentumPct"), [points]);
  const amount = useMemo(() => buildHistorySegments(points, "amountActivityPct"), [points]);
  const hovered = hoverIndex === null ? null : points[hoverIndex] ?? null;
  const handlePointer = (event: React.MouseEvent<SVGSVGElement>) => {
    if (points.length === 0) return;
    const mapped = clientPointToViewBox(event.clientX, event.clientY, event.currentTarget.getBoundingClientRect(), 924, 126);
    const ratio = Math.max(0, Math.min(1, (mapped.x - 48) / (856)));
    setHoverIndex(Math.round(ratio * (points.length - 1)));
  };
  const hoverX = hoverIndex === null || points.length <= 1 ? null : 48 + hoverIndex / (points.length - 1) * 856;
  return <div className="price-volume-history-plots" onMouseLeave={() => setHoverIndex(null)}>
    <HistorySvg ariaLabel={`滚动${period}日区间涨跌幅历史趋势`} color="var(--cs-color-market-up)" geometry={price} hoverIndex={hoverIndex} hoverX={hoverX} label={`滚动 ${period} 日区间涨跌幅`} onMouseMove={handlePointer} points={points} showDates={false} />
    <HistorySvg ariaLabel={`滚动${period}日成交活跃度历史趋势`} color="var(--cs-color-info)" geometry={amount} hoverIndex={hoverIndex} hoverX={hoverX} label={`滚动 ${period} 日成交活跃度`} onMouseMove={handlePointer} points={points} showDates />
    {hovered ? <div className={`price-volume-history-tooltip ${hoverIndex !== null && hoverIndex > points.length * .72 ? "left" : "right"}`} role="tooltip"><strong>{hovered.tradeDate}</strong><span>区间涨跌幅 <b className="num up">{formatPercent(hovered.priceMomentumPct)}</b></span><span>成交活跃度 <b className="num amount-value">{formatPercent(hovered.amountActivityPct)}</b></span></div> : null}
  </div>;
}

function HistorySvg({ ariaLabel, color, geometry, hoverIndex, hoverX, label, onMouseMove, points, showDates }: { ariaLabel: string; color: string; geometry: ReturnType<typeof buildHistorySegments>; hoverIndex: number | null; hoverX: number | null; label: string; onMouseMove: (event: React.MouseEvent<SVGSVGElement>) => void; points: PriceVolumeHistoryPointViewModel[]; showDates: boolean }) {
  return <svg aria-label={ariaLabel} className="price-volume-history-svg" role="img" viewBox="0 0 924 126" onMouseMove={onMouseMove}>
    <title>{ariaLabel}</title><text className="history-label" x="4" y="13">{label}</text>
    {[24, 63, 102].map((y) => <line className="grid-line" key={y} x1="48" x2="904" y1={y} y2={y} />)}
    {geometry.segments.map((segment, index) => <polyline fill="none" key={index} points={segment.map((point) => `${point.x},${point.y}`).join(" ")} stroke={color} strokeWidth="2" />)}
    {hoverX !== null ? <line className="history-crosshair" x1={hoverX} x2={hoverX} y1="18" y2="106" /> : null}
    {hoverIndex !== null && geometry.mapped[hoverIndex] ? <circle className="history-hover-point" cx={geometry.mapped[hoverIndex]!.x} cy={geometry.mapped[hoverIndex]!.y} fill={color} r="4" /> : null}
    {showDates ? dateLabels(points).map((item) => <text className="history-date-label" key={item.index} textAnchor={item.index === 0 ? "start" : item.index === points.length - 1 ? "end" : "middle"} x={points.length <= 1 ? 48 : 48 + item.index / (points.length - 1) * 856} y="122">{item.label}</text>) : null}
    <rect fill="transparent" height="104" width="856" x="48" y="16" />
  </svg>;
}

function dateLabels(points: PriceVolumeHistoryPointViewModel[]) { if (!points.length) return []; const indices = new Set([0, Math.round((points.length - 1) * .25), Math.round((points.length - 1) * .5), Math.round((points.length - 1) * .75), points.length - 1]); return [...indices].sort((a, b) => a - b).map((index) => ({ index, label: points[index]!.tradeDate.slice(5) })); }
function formatPercent(value: number | null) { if (value === null) return "--"; return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`; }
