import { useState } from "react";
import type { AccountSummary, TradeInput } from "../api/generatedContracts";
import { formatBeijingInstant, validateEntryDraft, type EntryDraft } from "../model/entryDraft";
import { useEntryContext } from "../model/useEntryContext";
import { useTradePreview } from "../model/useTradePreview";
import type { AccountingWriteSession } from "./AccountingWriteFlow";
import { EntryFields } from "./EntryFields";
import { TradingAssistantAction, TradingAssistantDialog, TradingAssistantField } from "./TradingAssistantForm";

export function LedgerEntryForm({ account, draft, onChange, session, onClose }: {
  account: AccountSummary; draft: EntryDraft; onChange: (draft: EntryDraft) => void; session: AccountingWriteSession; onClose: () => void;
}) {
  const [submitted, setSubmitted] = useState(false);
  const checked = validateEntryDraft(draft);
  const context = useEntryContext(account.accountId, draft.date, draft.kind === "TRADE" ? draft.stock?.tsCode : undefined);
  const trade = draft.kind === "TRADE" ? checked.input as TradeInput | null : null;
  const preview = useTradePreview(account.accountId, trade ? { tsCode: trade.tsCode, direction: trade.direction, tradeDate: trade.tradeDate, price: trade.price, quantity: trade.quantity } : null);
  const errors = [...(submitted ? checked.errors : []), ...(preview.data?.fieldErrors ?? []), ...session.fieldErrors];
  const title = draft.kind === "CASH" ? "记录资金变动" : draft.direction === "BUY" ? "记录买入" : "记录卖出";
  const previewReady = draft.kind === "CASH" || (preview.data?.calendarDataStatus === "Ready" && !preview.data.fieldErrors.length);
  const locked = !session.canSave;
  return <TradingAssistantDialog variant="drawer" title={title} subtitle={`${account.brokerName} · ${account.name}`} onClose={onClose}
    footer={<><TradingAssistantAction onClick={onClose}>{session.busy && session.recovery ? "稍后查看" : "取消"}</TradingAssistantAction>
      <TradingAssistantAction primary disabled={locked || context.loading || context.failed || preview.loading || preview.failed} onClick={() => {
        setSubmitted(true);
        if (!checked.input || !context.data || !previewReady) return;
        void session.save(draft.kind === "TRADE" ? "TRADE_CREATE" : "CASH_FLOW_CREATE", checked.input);
      }}>{session.busy && session.recovery ? "保存中…" : draft.kind === "CASH" ? "保存资金变动" : draft.direction === "BUY" ? "保存买入" : "保存卖出"}</TradingAssistantAction></>}>
    <EntryFields draft={draft} onChange={onChange} disabled={locked} errors={errors} initializedOn={account.initializedOn} />
    {draft.kind === "TRADE" && <>
      <TradingAssistantField label="预计佣金" readOnly value={preview.data?.commissionAmount ?? "—"} />
      {draft.direction === "SELL" && <TradingAssistantField label="预计印花税" readOnly value={preview.data?.stampTaxAmount ?? "—"} />}
      {context.data?.availableQuantity !== null && context.data?.availableQuantity !== undefined &&
        <p className="ta-note">{draft.date} 可卖数量：<span className="num">{context.data.availableQuantity}</span> 股</p>}
    </>}
    <TradingAssistantField label="备注（选填）" value={draft.note} disabled={locked} error={errors.find(e => e.field === "note")?.message}
      onChange={event => onChange({ ...draft, note: event.target.value })} />
    {draft.kind === "CASH" && <div className="ta-notice"><strong>资金进出不影响收益</strong>仅改变账户现金余额；不计入收益金额，未参与交易的资金不计入收益率分母。</div>}
    {context.data && <p className="ta-note">可用现金 <span className="num">{context.data.availableCash}</span> · 截至 {formatBeijingInstant(context.data.cashThrough)}</p>}
    {context.data?.reason && <p className="ta-note">{context.data.reason}</p>}
    {context.failed && <p className="ta-form-error" role="alert">暂时无法读取录入依据。<button type="button" className="ta-text-action" onClick={context.retry}>重新读取</button></p>}
    {preview.failed && <p className="ta-form-error" role="alert">暂时无法计算费用预览。<button type="button" className="ta-text-action" onClick={preview.retry}>重新读取</button></p>}
    {session.busy && session.recovery && <p className="ta-note">正在保存，请勿重复提交。输入尚未安全保留，请勿刷新或关闭页面。</p>}
  </TradingAssistantDialog>;
}
