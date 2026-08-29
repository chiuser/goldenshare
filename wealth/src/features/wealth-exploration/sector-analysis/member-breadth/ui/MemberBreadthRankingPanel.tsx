import type { SectorMemberBreadthController } from "../model/useSectorMemberBreadthController";
import type { SectorMemberBreadthRankingsViewModel, SectorMemberBreadthUrlState } from "../model/sectorMemberBreadthTypes";

export function MemberBreadthRankingPanel({ controller, rankings, state }: { controller: SectorMemberBreadthController; rankings: SectorMemberBreadthRankingsViewModel; state: SectorMemberBreadthUrlState }) {
  return <section className="member-breadth-ranking-panel">
    <header><div><strong>{scopeTitle(rankings)}</strong><span>{metricLabel(state)} · {state.direction === "up" ? "上涨广度" : "下跌广度"}</span></div><span>{rankings.totalSectorCount} 个行业 · {rankings.eligibleSectorCount} 个可排名</span></header>
    <div className="member-breadth-ranking-table" role="table" aria-label="成员广度完整行业榜">
      <div className="member-breadth-ranking-grid member-breadth-ranking-header" role="row"><span>行业</span><span>{metricLabel(state)}</span><span>名次</span><span>可计算 / 来源</span><span /></div>
      <div className="member-breadth-ranking-viewport">
        {rankings.rows.map((row) => <div className={`member-breadth-ranking-grid member-breadth-ranking-row ${state.sectorCode === row.sectorCode ? "selected" : ""}`} key={row.sectorCode} role="row">
          <button aria-label={`选择${row.sectorName}`} className="member-breadth-row-select" title={row.hierarchyPath} type="button" onClick={() => controller.selectSector(row.sectorCode)}><span className="member-breadth-industry-name"><strong>{row.sectorName}</strong><small>{row.hierarchyPath}</small></span><span className={row.metricValuePct === null ? "muted num" : "num brand"}>{row.metricText}</span><span className="num">{row.rankText}</span><span className="member-breadth-coverage"><b>{row.calculableCount} / {row.sourceMemberCount}</b><small>{row.coveragePct.toFixed(1)}%</small></span></button>
          {row.industryLevel < 3 ? <button aria-label={`下钻${row.sectorName}`} className="member-breadth-drill" type="button" onClick={() => controller.drillDown(row)}>›</button> : <span />}
          {row.qualificationStatus === "INELIGIBLE" ? <span className="member-breadth-sample-chip">样本不足</span> : null}
        </div>)}
      </div>
    </div>
  </section>;
}
function scopeTitle(rankings: SectorMemberBreadthRankingsViewModel) { if (rankings.scope === "LEVEL_1") return "一级行业成员广度"; if (rankings.scope === "LEVEL_2") return "二级行业成员广度"; if (rankings.scope === "LEVEL_3") return "三级行业成员广度"; if (rankings.scope === "LEVEL_1_CHILDREN") return `${rankings.parentSelection.level1Name ?? "一级行业"}内二级行业`; return `${rankings.parentSelection.level2Name ?? "二级行业"}内三级行业`; }
function metricLabel(state: SectorMemberBreadthUrlState) { return state.metric === "member-count" ? "成分股占比" : state.metric === "turnover" ? "成交额占比" : `MA${state.maPeriod}位置占比`; }
