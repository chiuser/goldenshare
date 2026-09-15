import { useState } from "react";
import type { AccountRef, CurvePoint } from "../api/generatedContracts";
import { returnChart } from "../model/returnChart";
import type { ReturnMetric } from "../model/returnSelection";
import { positionNumber as money, positionPercent as percent, profitTone } from "../model/positionPresentation";

export function ReturnCurveChart({ points, metric, accounts }: { points: CurvePoint[]; metric: ReturnMetric; accounts:AccountRef[] }) {
  const [hovered, setHovered] = useState<number | null>(null);
  const chart = returnChart(points, metric);
  const paths: string[] = [];
  let path = "";
  for (const p of chart.points) {
    if (p.y === null) { if (path) paths.push(path); path = ""; }
    else path += `${path ? " L" : "M"}${p.x},${p.y}`;
  }
  if (path) paths.push(path);
  const selected = hovered === null ? null : chart.points[hovered];
  return <div className="ta-return-chart" onMouseLeave={() => setHovered(null)}>
    <svg viewBox="0 0 940 380" role="img" aria-label={metric === "RATE" ? "期间收益率曲线" : "期间收益金额曲线"}>
      {chart.ticks.map(t => <g key={t.text}><line x1="120" x2="900" y1={t.y} y2={t.y} className={t.zero ? "ta-return-zero" : "ta-return-grid"} /><text x="105" y={t.y + 4} textAnchor="end">{t.text}</text></g>)}
      {paths.map((d, i) => <path key={i} d={d} fill="none" className="ta-return-line" />)}
      {chart.points.map((p, i) => <g key={p.point.periodStartDate}>
        {p.y !== null && <circle cx={p.x} cy={p.y} r="3" className="ta-return-dot" />}
        {(i % Math.max(1, Math.ceil(points.length / 6)) === 0 || i === points.length - 1) && <text x={p.x} y="360" textAnchor="middle">{p.point.periodStartDate}{p.point.periodEndDate !== p.point.periodStartDate && `—${p.point.periodEndDate.slice(5)}`}</text>}
        <rect x={p.x - 390 / Math.max(1, points.length)} y="10" width={780 / Math.max(1, points.length)} height="330" fill="transparent" tabIndex={0}
          role="button" aria-label={`${p.point.periodStartDate} 至 ${p.point.periodEndDate} ${p.point.profitAmount === null ? p.point.reason || "待计算" : money(p.point.profitAmount, true)}`}
          onMouseEnter={() => setHovered(i)} onFocus={() => setHovered(i)} onBlur={() => setHovered(null)} />
      </g>)}
    </svg>
    {selected && <div role="tooltip" className={`ta-return-tooltip ${selected.x > 470 ? "left" : "right"}`}>
      <span>{selected.point.periodStartDate}—{selected.point.periodEndDate}{!selected.point.isPeriodEnded && " · 未结束"}</span>
      <strong className={profitTone(selected.point.profitAmount)}>收益率 {percent(selected.point.returnPct, true)}</strong>
      <span>收益金额 {money(selected.point.profitAmount, true)}</span><span>参与成本 {money(selected.point.capitalAmount)}</span>
      {selected.point.accounts.map(account=><span key={account.accountId}>{accounts.find(a=>a.accountId===account.accountId)?.name} · 实际计算 {account.effectiveStartDate ?? "尚无起点"}—{account.calculatedThroughDate ?? "尚未完成"}</span>)}
      {selected.point.reason && <span>{selected.point.reason}</span>}
    </div>}
  </div>;
}
