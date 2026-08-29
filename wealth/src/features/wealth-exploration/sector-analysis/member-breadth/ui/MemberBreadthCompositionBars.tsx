import type { SectorMemberBreadthComposition, SectorMemberBreadthDirection, SectorMemberBreadthMaPeriod } from "../model/sectorMemberBreadthTypes";

export function MemberBreadthCompositionBars({ compositions, direction, maPeriod }: { compositions: SectorMemberBreadthComposition[]; direction: SectorMemberBreadthDirection; maPeriod: SectorMemberBreadthMaPeriod }) {
  return <section className="member-breadth-compositions" aria-label="三项成员广度组成">{compositions.map((item) => <Composition key={item.metric} item={item} direction={direction} maPeriod={maPeriod} />)}</section>;
}
function Composition({ item, direction, maPeriod }: { item: SectorMemberBreadthComposition; direction: SectorMemberBreadthDirection; maPeriod: SectorMemberBreadthMaPeriod }) {
  const labels = item.metric === "MA_POSITION" ? [`站上MA${maPeriod}`, "等于均线", `跌破MA${maPeriod}`] : item.metric === "TURNOVER" ? ["上涨成交额", "平盘成交额", "下跌成交额"] : ["上涨成分股", "平盘成分股", "下跌成分股"];
  const values = [item.positivePct, item.neutralPct, item.negativePct]; const directionValue = direction === "UP" ? item.positivePct : item.negativePct;
  return <article><header><strong>{title(item.metric, maPeriod)}</strong><span>{directionValue === null ? "--" : `${directionValue.toFixed(1)}%`}</span></header>{values[0] === null ? <div className="member-breadth-composition-empty">样本不足 · {item.calculableCount}/{item.sourceCount}</div> : <><div className="member-breadth-composition-bar" aria-label={`${title(item.metric, maPeriod)}组成`}><i className="positive" style={{ width: `${values[0]}%` }} /><i className="neutral" style={{ width: `${values[1]}%` }} /><i className="negative" style={{ width: `${values[2]}%` }} /></div><div className="member-breadth-composition-legend">{labels.map((label, index) => <span key={label}><i className={index === 0 ? "positive" : index === 1 ? "neutral" : "negative"} />{label} {values[index]!.toFixed(1)}%</span>)}</div></>}</article>;
}
function title(metric: string, maPeriod: number) { return metric === "MEMBER_COUNT" ? "成分股数量广度" : metric === "TURNOVER" ? "成交额参与广度" : `MA${maPeriod}位置广度`; }
