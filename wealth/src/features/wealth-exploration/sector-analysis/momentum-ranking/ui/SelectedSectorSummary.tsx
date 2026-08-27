import { formatPercentile, formatRank, formatReturnPct } from "../api/sectorMomentumAdapter";
import type { SectorMomentumDetailResponse } from "../model/sectorMomentumTypes";

export function SelectedSectorSummary({ detail }: { detail: SectorMomentumDetailResponse }) {
  const directionClass = detail.returnPct === null ? "muted" : detail.returnPct > 0 ? "up" : detail.returnPct < 0 ? "down" : "flat";
  return (
    <section className="momentum-selected-summary" aria-label={`${detail.sectorName}详情摘要`}>
      <div className="momentum-selected-identity">
        <div>
          <strong>{detail.sectorName}</strong>
          <span className="momentum-level-chip">{detail.industryLevel}级行业</span>
        </div>
        <span title={detail.hierarchyPath}>{detail.hierarchyPath}</span>
      </div>
      <SummaryMetric label="同组强度排名" value={formatRank(detail.currentScopeStrengthRank, detail.currentScopeCalculableCount)} />
      <SummaryMetric className={directionClass} label="区间涨跌幅" value={formatReturnPct(detail.returnPct)} />
      <SummaryMetric label="组内分位" value={formatPercentile(detail.percentile)} />
      {detail.industryLevel > 1 ? (
        <>
          <SummaryMetric label="全层级排名" value={formatRank(detail.globalLevelStrengthRank, detail.globalLevelCalculableCount)} />
          <SummaryMetric label="直属父级排名" value={formatRank(detail.parentStrengthRank, detail.parentCalculableCount ?? 0)} />
        </>
      ) : null}
    </section>
  );
}

function SummaryMetric({ label, value, className = "" }: { label: string; value: string; className?: string }) {
  return (
    <div className="momentum-summary-metric">
      <span>{label}</span>
      <strong className={`num ${className}`}>{value}</strong>
    </div>
  );
}
