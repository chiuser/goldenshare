import { useState } from "react";
import type { RecordCategory, RecordFilter } from "../model/recordsQuery";
import { TradingAssistantAction, TradingAssistantField } from "./TradingAssistantForm";
import { TradingAssistantStockPicker } from "./TradingAssistantStockPicker";

export function RecordFilters({ category, initial, onQuery, onReset }: { category: RecordCategory; initial: RecordFilter;
  onQuery: (filter: RecordFilter) => void; onReset: () => void }) {
  const [draft, setDraft] = useState(initial);
  const [error, setError] = useState("");
  const directions = category === "CASH" ? [["IN", "转入"], ["OUT", "转出"]] : [["BUY", "买入"], ["SELL", "卖出"]];
  return <form className="ta-record-filters" onSubmit={event => { event.preventDefault();
    if (!draft.start || !draft.end || draft.start > draft.end) { setError("结束日期不得早于开始日期"); return; }
    setError(""); onQuery(draft);
  }}>
    <TradingAssistantField label="开始日期" type="date" required value={draft.start} onChange={e => setDraft({ ...draft, start: e.target.value })} />
    <TradingAssistantField label="结束日期" type="date" required value={draft.end} error={error} onChange={e => setDraft({ ...draft, end: e.target.value })} />
    {category !== "CASH" && <TradingAssistantStockPicker value={draft.stock} onChange={stock => setDraft({ ...draft, stock })} optional />}
    {category !== "CLOSED" && <label className="ta-field">{category === "CASH" ? "资金方向" : "成交方向"}<select aria-label={category === "CASH" ? "资金方向" : "成交方向"} value={draft.direction} onChange={e => setDraft({ ...draft, direction: e.target.value })}>
      <option value="">全部方向</option>{directions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}
    <div className="ta-record-filter-actions"><TradingAssistantAction primary type="submit">查询</TradingAssistantAction><TradingAssistantAction onClick={onReset}>重置</TradingAssistantAction></div>
  </form>;
}
