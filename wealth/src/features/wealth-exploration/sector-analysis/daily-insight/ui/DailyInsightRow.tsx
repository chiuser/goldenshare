import type { DailyInsightRowViewModel } from "../api/sectorDailyInsightTypes";

interface Props {
  row: DailyInsightRowViewModel;
  selected: boolean;
  onSector: (row: DailyInsightRowViewModel) => void;
  onExplain: (row: DailyInsightRowViewModel, trigger: HTMLButtonElement) => void;
}
export function DailyInsightRow({ row, selected, onSector, onExplain }: Props) {
  return <div className="daily-insight-row daily-insight-columns" role="row">
    <div className="daily-insight-identity" role="cell"><button type="button" title={row.sectorName} onClick={() => onSector(row)}>{row.sectorName}</button><span title={row.hierarchyPath}>{row.hierarchyPath}</span></div>
    {row.returns.map((value, index) => <div className="daily-insight-number" role="cell" key={index}><span className={`num ${value.direction}`}>{value.text}</span></div>)}
    <div className="daily-insight-number" role="cell"><span className="num">{row.rankText}</span></div>
    <div className="daily-insight-fact-cell" role="cell"><span className="daily-insight-fact-tag">{row.eventLabel}</span></div>
    <div className="daily-insight-reason-cell" role="cell"><button type="button" className={`daily-insight-reason${selected ? " selected" : ""}`} aria-label={`查看${row.sectorName}说明`} aria-haspopup="dialog" aria-expanded={selected} title={row.renderedText} onClick={(event) => onExplain(row, event.currentTarget)}>{row.renderedText}</button></div>
  </div>;
}
