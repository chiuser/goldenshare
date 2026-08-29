import type { SectorMemberBreadthDetailsViewModel } from "../model/sectorMemberBreadthTypes";

export function MemberBreadthSelectedSummary({ details, pending }: { details: SectorMemberBreadthDetailsViewModel; pending: boolean }) {
  return <section aria-label={`${details.sectorName}成员广度摘要`} className={`member-breadth-summary ${pending ? "pending" : ""}`}>
    <div className="member-breadth-summary-identity"><div><strong title={details.sectorName}>{details.sectorName}</strong><span>{details.industryLevel}级行业</span></div><small title={details.hierarchyPath}>{details.hierarchyPath}</small></div>
    <div className="member-breadth-summary-metrics">{details.compositions.map((item) => <div key={item.metric}><span>{label(item.metric)}</span><strong>{item.calculableCount} / {item.sourceCount}</strong><small>覆盖 {item.coveragePct.toFixed(1)}%{item.eligible ? "" : " · 样本不足"}</small></div>)}</div>
    {pending ? <span className="member-breadth-pending">正在更新所选事实</span> : null}
  </section>;
}
function label(metric: string) { return metric === "MEMBER_COUNT" ? "成分股可计算" : metric === "TURNOVER" ? "成交额可计算" : "均线位置可计算"; }
