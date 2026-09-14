import { useEffect, useState } from "react";
import type { RoundRecordsScope, TradeDayGroup } from "../api/generatedContracts";
import { getCashDetail, getTradeDetail, TradingAssistantApiError } from "../api/tradingAssistantApi";
import { getAuthEpoch } from "../../auth/model/authStorage";
import { closedFacts, type RecordSelection } from "../model/recordPresentation";
import { positionNumber as money, positionPercent as percent, positionQuantity as quantity, profitTone } from "../model/positionPresentation";
import { RecordDetailContent, type SavedRecordDetail } from "./RecordDetailDialog";
import type { MaintenanceRecord } from "./RecordMaintenanceForm";
import { TradingAssistantAction } from "./TradingAssistantForm";

export function RecordDetails({ selection, token, onRefresh, onGroup, onRound, onMaintain }: {
  selection: RecordSelection; token: string; onRefresh: () => void; onGroup: (group: TradeDayGroup) => void;
  onRound: (round: RoundRecordsScope) => void; onMaintain: (source: MaintenanceRecord, action: "CORRECT" | "VOID") => void;
}) {
  const [detail, setDetail] = useState<SavedRecordDetail | null>(null);
  const [error, setError] = useState(false);
  const [original, setOriginal] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    setDetail(null); setError(false);
    if (selection.kind === "DAY" || (selection.kind === "CLOSED" && !original)) return;
    const abort = new AbortController(), epoch = getAuthEpoch();
    const work = selection.kind === "CASH" ? getCashDetail(selection.record.accountRef.accountId, selection.record.cashFlowId, abort.signal, { readContext: token })
      .then(value => ({ kind: "CASH_FLOW" as const, detail: value }))
      : getTradeDetail(selection.record.accountRef.accountId, selection.record.tradeId, abort.signal, { readContext: token }).then(value => ({ kind: "TRADE" as const, detail: value }));
    void work.then(value => { if (!abort.signal.aborted && epoch === getAuthEpoch()) setDetail(value); }).catch(reason => {
      if (abort.signal.aborted || epoch !== getAuthEpoch()) return;
      if (reason instanceof TradingAssistantApiError && reason.details.code === "TA_READ_CONTEXT_CHANGED") onRefresh();
      else setError(true);
    });
    return () => abort.abort();
  }, [selection, token, original, retry]);
  if (selection.kind === "DAY") {
    const r = selection.record;
    return <><h3>{r.stockRef.name} · 当日汇总</h3><p className="ta-note">{r.stockRef.tsCode} · {r.accountRef.name} · {r.tradeDate}</p>
      <div className={`ta-record-profit ta-profit--${profitTone(r.closedProfitAmount)}`}><strong>{money(r.closedProfitAmount, true)}</strong><span>{percent(r.closedReturnPct, true)}</span></div>
      {r.reason && <p className="ta-note">{r.reason}</p>}
      <dl className="ta-record-facts"><dt>成交数量</dt><dd>{quantity(r.quantity)} 股</dd><dt>成交均价</dt><dd>{money(r.averagePrice)}</dd><dt>成交金额</dt><dd>{money(r.grossAmount)}</dd><dt>现金变动</dt><dd>{money(r.netCashChange, true)}</dd></dl>
      <TradingAssistantAction onClick={() => onGroup(r)}>查看 {r.tradeCount} 笔原始成交</TradingAssistantAction></>;
  }
  if (selection.kind === "CLOSED" && !original) {
    const r = selection.record;
    return <><h3>{r.stockRef.name} · 逐笔闭环</h3><p className="ta-note">{r.stockRef.tsCode}</p><div className={`ta-record-profit ta-profit--${profitTone(r.profitAmount)}`}><strong>{money(r.profitAmount, true)}</strong><span>{percent(r.returnPct, true)}</span></div>
      <div className="ta-record-detail-scroll"><dl className="ta-record-facts">{closedFacts(r).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></div>
      <TradingAssistantAction onClick={() => setOriginal(true)}>查看原始成交</TradingAssistantAction>
      <TradingAssistantAction onClick={() => onRound({ accountId: r.roundRef.accountId, roundId: r.roundRef.roundId })}>查看第 {r.roundRef.roundNumber} 轮全部闭环</TradingAssistantAction></>;
  }
  return <>{original && <TradingAssistantAction onClick={() => setOriginal(false)}>返回闭环详情</TradingAssistantAction>}
    {error ? <><p role="alert">原始详情暂时无法读取。</p><TradingAssistantAction onClick={() => setRetry(v => v + 1)}>重新读取</TradingAssistantAction></>
      : detail ? <RecordDetailContent value={detail} onMaintain={onMaintain} /> : <p role="status">正在读取原始详情…</p>}</>;
}
