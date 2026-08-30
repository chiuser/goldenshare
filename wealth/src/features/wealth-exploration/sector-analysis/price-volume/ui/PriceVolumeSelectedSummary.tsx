import type { SectorPriceVolumeController } from "../model/useSectorPriceVolumeController";

export function PriceVolumeSelectedSummary({ controller }: { controller: SectorPriceVolumeController }) {
  const row = controller.selectedRow;
  if (!row) return <section className="price-volume-selected-summary price-volume-selected-empty"><span>请选择一个二维坐标可计算行业</span></section>;
  const rank = controller.urlState?.sortBy === "amount-activity" ? row.amountRank : row.priceRank;
  const rankable = controller.urlState?.sortBy === "amount-activity" ? row.amountRankableCount : row.priceRankableCount;
  return (
    <section className="price-volume-selected-summary" aria-label="当前选中行业摘要">
      <div className="price-volume-summary-identity"><strong title={row.sectorName}>{row.sectorName}</strong><small title={row.hierarchyPath}>{row.hierarchyPath}</small></div>
      <SummaryMetric label="区间涨跌幅" value={row.priceText} className={row.priceMomentumPct === null ? "muted" : row.priceMomentumPct >= 0 ? "up" : "down"} />
      <SummaryMetric label="成交活跃度" value={row.amountText} className="amount-value" />
      <SummaryMetric label="横向名次" value={rank === null ? "--" : `${rank} / ${rankable}`} />
      <div className="price-volume-summary-status"><span>当前状态</span><strong className={`price-volume-status-chip ${row.stateClass}`}><i aria-hidden="true" />{row.stateText}</strong></div>
    </section>
  );
}
function SummaryMetric({ label, value, className = "" }: { label: string; value: string; className?: string }) { return <div className="price-volume-summary-metric"><span>{label}</span><strong className={`num ${className}`}>{value}</strong></div>; }
