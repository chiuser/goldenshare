import { MetricCard } from "../../../../../shared/ui/MetricCard";
import { Panel } from "../../../../../shared/ui/Panel";
import { DAILY_LEVEL_LABELS } from "../api/sectorDailyInsightAdapter";
import type { DailyInsightSnapshotViewModel } from "../api/sectorDailyInsightTypes";

export function DailyInsightOverview({ snapshot }: { snapshot: DailyInsightSnapshotViewModel }) {
  return <Panel title="当日板块事实" className="daily-insight-overview" meta={<div className="daily-insight-overview-meta">{snapshot.missingText ? <span className="daily-insight-missing" title={snapshot.missingText}>{snapshot.missingText}</span> : null}<span>{DAILY_LEVEL_LABELS[snapshot.facts.industryLevel]} · {snapshot.facts.summary.sectorCount} 个</span></div>}>
    <div className="daily-insight-cards">{snapshot.overview.map((item) => <MetricCard key={item.label} label={item.label} value={<span className={`num daily-insight-tone-${item.tone}`}>{item.value}</span>} sub={item.note} className="daily-insight-card" />)}</div>
  </Panel>;
}
