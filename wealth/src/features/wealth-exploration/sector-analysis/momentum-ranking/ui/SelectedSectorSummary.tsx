import { useLayoutEffect, useRef } from "react";

import { formatPercentile, formatRank, formatReturnPct } from "../api/sectorMomentumAdapter";
import type { SectorMomentumDetailResponse } from "../model/sectorMomentumTypes";

export function SelectedSectorSummary({ detail }: { detail: SectorMomentumDetailResponse }) {
  const identityRef = useRef<HTMLDivElement>(null);
  const nameRef = useRef<HTMLElement>(null);
  const pathRef = useRef<HTMLSpanElement>(null);
  const directionClass = detail.returnPct === null ? "muted" : detail.returnPct > 0 ? "up" : detail.returnPct < 0 ? "down" : "flat";

  useLayoutEffect(() => {
    const identity = identityRef.current;
    const name = nameRef.current;
    const path = pathRef.current;
    if (!identity || !name || !path) return;

    const updateCompactState = () => {
      identity.classList.remove("compact", "extra-compact");
      const overflows = () => name.scrollWidth > name.clientWidth || path.scrollWidth > path.clientWidth;
      if (!overflows()) return;

      identity.classList.add("compact");
      if (overflows()) identity.classList.add("extra-compact");
    };

    updateCompactState();
    if (typeof ResizeObserver === "undefined") return;

    const observer = new ResizeObserver(updateCompactState);
    observer.observe(identity);
    return () => observer.disconnect();
  }, [detail.hierarchyPath, detail.industryLevel, detail.sectorName]);

  return (
    <section className="momentum-selected-summary" aria-label={`${detail.sectorName}详情摘要`}>
      <div className="momentum-selected-identity" ref={identityRef}>
        <div>
          <strong ref={nameRef}>{detail.sectorName}</strong>
          <span className="momentum-level-chip">{detail.industryLevel}级行业</span>
        </div>
        <span ref={pathRef} title={detail.hierarchyPath}>{detail.hierarchyPath}</span>
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
