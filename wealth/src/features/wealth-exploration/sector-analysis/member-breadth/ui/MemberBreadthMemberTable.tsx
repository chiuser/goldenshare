import type { SectorMemberBreadthDetailsViewModel } from "../model/sectorMemberBreadthTypes";

export function MemberBreadthMemberTable({ details }: { details: SectorMemberBreadthDetailsViewModel }) {
  return <section className="member-breadth-member-panel"><header><div><strong>{details.sectorName}成分股明细</strong><span>{details.members.length} 只来源成分股</span></div><span>{details.tradeDate} · MA{details.maPeriod}</span></header>
    <div className="member-breadth-member-table" role="table" aria-label="成员广度成分股完整明细"><div className="member-breadth-member-grid member-breadth-member-header" role="row"><span>股票</span><span>当日涨跌幅</span><span>当日成交额</span><span>成交额贡献</span><span>均线位置</span><span>距均线</span></div><div className="member-breadth-member-viewport">{details.members.map((row) => <div className="member-breadth-member-grid member-breadth-member-row" key={row.stockCode} role="row"><span className="member-breadth-stock"><strong title={row.stockName ?? row.stockCode}>{row.stockName ?? "--"}</strong><small>{row.stockCode}</small></span><span className={`num ${tone(row.dailyPctChg)}`}>{signedPct(row.dailyPctChg)}</span><span className="num">{amount(row.amountThousandYuan)}</span><span className="num">{pct(row.amountContributionPct)}</span><span>{relation(row.maRelation, details.maPeriod)}</span><span className={`num ${tone(row.maDistancePct)}`}>{signedPct(row.maDistancePct)}</span></div>)}</div></div>
  </section>;
}
function signedPct(value: number | null) { return value === null ? "--" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`; }
function pct(value: number | null) { return value === null ? "--" : `${value.toFixed(2)}%`; }
function tone(value: number | null) { return value === null ? "muted" : value > 0 ? "up" : value < 0 ? "down" : "flat"; }
function amount(value: number | null) { if (value === null) return "--"; if (value >= 100000) return `${(value / 100000).toFixed(2)}亿`; if (value >= 10) return `${(value / 10).toFixed(2)}万`; return `${value.toFixed(2)}千元`; }
function relation(value: "ABOVE" | "EQUAL" | "BELOW" | null, period: number) { return value === null ? "--" : value === "ABOVE" ? `站上MA${period}` : value === "BELOW" ? `跌破MA${period}` : `等于MA${period}`; }
