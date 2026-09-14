import { useState } from "react";
import type { AllocationSlice, PositionRow, PositionsResponse } from "../api/generatedContracts";
import { fixedUnits, geometryFraction, positionNumber as number, positionPercent as percent, profitTone, sortPositions } from "../model/positionPresentation";
import { pieSector, positionTiles } from "../model/positionGeometry";

export type GraphicView = "bar" | "pie" | "map";
const label = (slice: AllocationSlice) => slice.kind === "CASH" ? "现金" : slice.kind === "OTHER" ? `其他 · ${slice.members.length} 只` : slice.stockRef!.name;
const rowLabel = (row: PositionRow) => `${row.stockRef.name} ${row.stockRef.tsCode} · 市值 ${number(row.marketValue)} · 收益 ${number(row.holdingProfitAmount, true)} · 收益率 ${percent(row.holdingReturnPct, true)} · 占比 ${percent(row.stockValueWeightPct)}`;
export function PositionsCharts({ data, view, onDetail }: { data: PositionsResponse; view: GraphicView; onDetail: (row: PositionRow) => void }) {
  const [assetBasis, setAssetBasis] = useState(false);
  const rows = sortPositions(data.items, "stockValueWeightPct");
  const slices = assetBasis ? data.allocation.totalAssetSlices : data.allocation.stockValueSlices;
  const open = (code: string) => { const row = rows.find(item => item.stockRef.tsCode === code); if (row) onDetail(row); };
  if (view === "pie") return <section className="ta-position-panel"><div className="ta-position-panel-heading"><h2>持仓构成 · {assetBasis ? "总资产口径" : "持仓市值口径"}</h2>
    <div className="ta-segments" role="group" aria-label="饼图资产口径"><button aria-pressed={!assetBasis} onClick={() => setAssetBasis(false)}>持仓市值</button><button aria-pressed={assetBasis} onClick={() => setAssetBasis(true)}>总资产（含现金）</button></div></div>
    {slices ? <PositionPie slices={slices} onOpen={open} /> : <p className="ta-position-empty">{rows.length ? "估值尚不完整，暂不生成持仓比例图" : "暂无股票持仓"}</p>}
  </section>;
  if (!data.summary.stockMarketValue || fixedUnits(data.summary.stockMarketValue) === 0n) return <section className="ta-position-panel"><h2>{view === "bar" ? "持仓占比" : "持仓盈亏地图"}</h2><p className="ta-position-empty">{rows.length ? "估值尚不完整，暂不生成持仓比例图" : "暂无股票持仓"}</p></section>;
  const max = rows.reduce((value, row) => row.stockValueWeightPct !== null && fixedUnits(row.stockValueWeightPct) > value ? fixedUnits(row.stockValueWeightPct) : value, 0n);
  const tiles = positionTiles(rows.map(row => ({ id: row.stockRef.tsCode, value: fixedUnits(row.marketValue!) })));
  return <div className={`ta-position-chart-grid ta-position-chart-grid--${view}`}><section className="ta-position-panel"><h2>{view === "bar" ? "持仓占比" : "持仓盈亏地图"}</h2><p className="ta-note">{rows.length} 只持仓 · {view === "bar" ? "条长表示占比，红盈绿亏" : "面积表示市值，颜色深浅表示收益率幅度"}</p>
    {view === "bar" ? <div className="ta-position-bars" tabIndex={0} aria-label="全部持仓条形图"><div className="ta-position-bar-scale"><span>0%</span><span>{percent(rows[0]?.stockValueWeightPct ?? null)}</span></div>
      {rows.map(row => <button type="button" key={row.stockRef.tsCode} className="ta-position-bar-row" onClick={() => onDetail(row)} title={rowLabel(row)}>
        <span>{row.stockRef.name}</span><span className="ta-position-bar-track"><i className={`ta-profit-bg--${profitTone(row.holdingProfitAmount)}`} style={{ width: `${geometryFraction(fixedUnits(row.stockValueWeightPct!), max) * 100}%` }} /></span>
        <span>{percent(row.stockValueWeightPct)}</span><span className={`ta-profit--${profitTone(row.holdingProfitAmount)}`}>{number(row.holdingProfitAmount, true)}</span></button>)}</div>
      : <svg className="ta-position-map" viewBox="0 0 1000 420" aria-label="持仓盈亏地图">{tiles.map(tile => { const row = rows.find(row => row.stockRef.tsCode === tile.id)!;
        const strength = row.holdingReturnPct === null ? 0n : fixedUnits(row.holdingReturnPct) < 0n ? -fixedUnits(row.holdingReturnPct) : fixedUnits(row.holdingReturnPct);
        const opacity = .25 + .6 * geometryFraction(strength > 2000n ? 2000n : strength, 2000n);
        const caption = `${percent(row.holdingReturnPct, true)} / ${percent(row.stockValueWeightPct)}`;
        const fits = tile.height >= 54 && tile.width >= Math.max(130, row.stockRef.name.length * 13 + 24, caption.length * 8 + 24);
        return <g key={tile.id} role="button" tabIndex={0} aria-label={rowLabel(row)} onClick={() => onDetail(row)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onDetail(row); } }}>
          <title>{rowLabel(row)}</title><rect x={tile.x} y={tile.y} width={tile.width} height={tile.height} className={`ta-profit-bg--${profitTone(row.holdingProfitAmount)}`} fillOpacity={opacity} />
          {fits && <text x={tile.x + 12} y={tile.y + tile.height / 2 - 4}><tspan>{row.stockRef.name}</tspan><tspan x={tile.x + 12} dy="22">{caption}</tspan></text>}</g>; })}</svg>}
  </section><aside className="ta-position-panel"><h2>读图方式</h2><p className="ta-profit--up">红色：当前持仓盈利</p><p className="ta-profit--down">绿色：当前持仓亏损</p><p>占比以股票持仓市值为分母，不包含现金。</p><p>点击股票查看分账户持仓与预计费用。</p>
    <div className="ta-position-chart-index" aria-label="全部持仓详情入口">{rows.map(row => <button type="button" key={row.stockRef.tsCode} onClick={() => onDetail(row)} title={rowLabel(row)}>{row.stockRef.name}<span>{percent(row.stockValueWeightPct)}</span></button>)}</div>
  </aside></div>;
}

function PositionPie({ slices, onOpen }: { slices: AllocationSlice[]; onOpen: (code: string) => void }) {
  const [active, setActive] = useState<number | null>(null);
  const total = slices.reduce((sum, item) => sum + fixedUnits(item.marketValue), 0n);
  let cumulative = 0n;
  return <div className="ta-position-pie" onMouseLeave={() => setActive(null)}>
    <svg viewBox="0 0 400 400" aria-label="持仓构成饼图">{slices.map((slice, i) => {
      const start = geometryFraction(cumulative, total) * Math.PI * 2; cumulative += fixedUnits(slice.marketValue);
      const end = geometryFraction(cumulative, total) * Math.PI * 2;
      return <path key={slice.stockRef?.tsCode ?? slice.kind} d={pieSector(start, end)} className={`ta-pie-color-${i}`} role="button" tabIndex={0}
        aria-label={`${label(slice)} ${number(slice.marketValue)} ${percent(slice.weightPct)}`} onFocus={() => setActive(i)} onMouseEnter={() => setActive(i)}
        onClick={() => slice.stockRef ? onOpen(slice.stockRef.tsCode) : setActive(i)} onKeyDown={event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); if (slice.stockRef) onOpen(slice.stockRef.tsCode); else setActive(i); } }}>
        <title>{label(slice)} · {number(slice.marketValue)} · {percent(slice.weightPct)}</title></path>;
    })}</svg>
    <div className="ta-position-pie-legend">{slices.map((slice, i) => <div key={slice.stockRef?.tsCode ?? slice.kind} onMouseEnter={() => setActive(i)}>
      <button type="button" onFocus={() => setActive(i)} onClick={() => slice.stockRef ? onOpen(slice.stockRef.tsCode) : setActive(active === i ? null : i)} aria-expanded={slice.kind === "OTHER" ? active === i : undefined}>
        <i className={`ta-pie-color-${i}`} /><span>{label(slice)}</span><span>{number(slice.marketValue)}</span><span>{percent(slice.weightPct)}</span></button>
      {slice.kind === "OTHER" && active === i && <div className="ta-position-other" role="region" aria-label="其他持仓完整明细" tabIndex={0}>
        {slice.members.map(member => <button type="button" key={member.stockRef.tsCode} onClick={() => onOpen(member.stockRef.tsCode)}><span>{member.stockRef.name} · {member.stockRef.tsCode}</span><span>{number(member.marketValue)}</span><span>{percent(member.weightPct)}</span></button>)}</div>}
    </div>)}</div>
  </div>;
}
