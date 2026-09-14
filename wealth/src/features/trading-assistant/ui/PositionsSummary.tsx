import type { PositionRow, PositionsSummary as Summary } from "../api/generatedContracts";
import { positionNumber as number, positionPercent as percent, profitTone } from "../model/positionPresentation";

export function PositionMetric({ title, value, note, tone = "flat" }: { title: string; value: string; note: string; tone?: string }) {
  return <div className={`ta-position-metric ta-position-metric--${tone}`}><h3>{title}</h3><strong>{value}</strong><small>{note}</small></div>;
}
export function PositionsSummary({ summary: s, graphical }: { summary: Summary; graphical: boolean }) {
  return <div className="ta-position-metrics" aria-label="持仓摘要">
    {graphical ? <>
      <PositionMetric title="持仓市值" value={number(s.stockMarketValue)} note={`占总资产 ${percent(s.stockAssetWeightPct)}`} tone="brand" />
      <PositionMetric title="现金" value={number(s.cashAmount)} note={`占总资产 ${percent(s.cashWeightPct)}`} />
      <PositionMetric title="最大持仓" value={s.largestPosition?.stockRef.name ?? "—"} note={`占持仓 ${percent(s.largestPosition?.weightPct ?? null)}`} />
      <PositionMetric title="前三集中度" value={percent(s.top3WeightPct)} note="前三大持仓占股票市值" />
    </> : <>
      <PositionMetric title="总资产" value={number(s.totalAssets)} note={`现金 ${number(s.cashAmount)}`} tone="brand" />
      <PositionMetric title="持仓市值" value={number(s.stockMarketValue)} note={`${s.positionCount ?? "—"} 只持仓 · 占总资产 ${percent(s.stockAssetWeightPct)}`} />
      <PositionMetric title="持仓收益" value={number(s.holdingProfitAmount, true)} note={percent(s.holdingReturnPct, true)} tone={profitTone(s.holdingProfitAmount)} />
      <PositionMetric title="当日收益" value={number(s.dayProfitAmount, true)} note={percent(s.dayReturnPct, true)} tone={profitTone(s.dayProfitAmount)} />
    </>}
  </div>;
}
export function PositionFees({ row }: { row: Pick<PositionRow, "estimatedSellCommission" | "estimatedStampTax" | "estimatedTotalFeeAmount" | "estimatedNetProceeds"> }) {
  return <div className="ta-position-metrics ta-position-fees" aria-label="预计卖出费用">
    <PositionMetric title="预计卖出佣金" value={number(row.estimatedSellCommission)} note="按当前账户费率" />
    <PositionMetric title="预计印花税" value={number(row.estimatedStampTax)} note="按当前印花税率" />
    <PositionMetric title="预计费用合计" value={number(row.estimatedTotalFeeAmount)} note="佣金与印花税" />
    <PositionMetric title="预计净变现价值" value={number(row.estimatedNetProceeds)} note="市值扣除预计费用" tone="brand" />
  </div>;
}
