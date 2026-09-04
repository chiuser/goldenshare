import { useLayoutEffect, useRef, useState } from "react";
import { Panel } from "../../../../../shared/ui/Panel";
import type { DailyInsightRowViewModel } from "../api/sectorDailyInsightTypes";
import { DailyInsightRow } from "./DailyInsightRow";

interface Props {
  title: string; subtitle: string; rows: DailyInsightRowViewModel[]; emptyMessage: string;
  selected: DailyInsightRowViewModel | null;
  onSector: (row: DailyInsightRowViewModel) => void;
  onExplain: (row: DailyInsightRowViewModel, trigger: HTMLButtonElement) => void;
}
export function DailyInsightPanel({ title, subtitle, rows, emptyMessage, selected, onSector, onExplain }: Props) {
  const viewport = useRef<HTMLDivElement>(null);
  const [headerWidth, setHeaderWidth] = useState<number>();
  useLayoutEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const measure = () => setHeaderWidth(element.clientWidth || undefined);
    const observer = new ResizeObserver(measure);
    observer.observe(element); measure();
    return () => observer.disconnect();
  }, [rows.length]);
  return <Panel title={title} className="daily-insight-panel" meta={<span className="daily-insight-sort-note">{subtitle}</span>}>
    <div role="table" aria-label={`${title}完整列表`}>
      <div role="rowgroup"><div className="daily-insight-columns daily-insight-header" role="row" style={{ width: headerWidth }}>
        {["行业 / 路径", "1日", "5日", "20日", "名次", "事实标签", "说明"].map((label, index) => <span key={label} role="columnheader" className={index > 0 && index < 6 ? "daily-insight-centered" : undefined}>{label}</span>)}
      </div></div>
      <div ref={viewport} className="daily-insight-scroll" role="rowgroup" tabIndex={0} aria-label={`${title}滚动列表`}>
        {rows.map((row) => <DailyInsightRow key={row.sectorCode} row={row} selected={selected === row} onSector={onSector} onExplain={onExplain} />)}
        {!rows.length ? <div className="daily-insight-local-empty" role="row"><span role="cell">{emptyMessage}</span></div> : null}
      </div>
    </div>
  </Panel>;
}
