import { useEffect, useRef, useState } from "react";
import type { AccountSummary, CashFlowRecord, CashCorrectionPreview, FieldErrorDto, TradeRecord, TradeCorrectionPreview } from "../api/generatedContracts";
import { accountPath, request, TradingAssistantApiError } from "../api/tradingAssistantApi";
import { validateEntryDraft, type EntryDraft } from "../model/entryDraft";
import type { AccountingWriteSession } from "./AccountingWriteFlow";
import { EntryFields } from "./EntryFields";
import { TradingAssistantAction, TradingAssistantDialog, TradingAssistantField } from "./TradingAssistantForm";

export type MaintenanceRecord = { kind: "TRADE"; record: TradeRecord } | { kind: "CASH_FLOW"; record: CashFlowRecord };
export function recordDraft(source: MaintenanceRecord): EntryDraft {
  const r = source.record;
  return source.kind === "TRADE" ? { kind: "TRADE", direction: source.record.direction, stock: source.record.stockRef,
    date: source.record.tradeDate, price: source.record.price, quantity: String(source.record.quantity), amount: "", note: r.note ?? "", noteWasNull: r.note === null }
    : { kind: "CASH", direction: source.record.direction, stock: null, date: source.record.occurredOn,
      price: "", quantity: "", amount: source.record.amount, note: r.note ?? "", noteWasNull: r.note === null };
}
type Review = { input: Record<string, unknown>; preview: TradeCorrectionPreview | CashCorrectionPreview };
export function RecordMaintenanceForm({ account, source, action, restored, session, onClose }: {
  account: AccountSummary; source: MaintenanceRecord; action: "CORRECT" | "VOID"; restored?: EntryDraft;
  session: AccountingWriteSession; onClose: () => void;
}) {
  const [draft, setDraft] = useState(() => restored ?? recordDraft(source));
  const [review, setReview] = useState<Review | null>(null);
  const [checking, setChecking] = useState(false);
  const [errors, setErrors] = useState<FieldErrorDto[]>([]);
  const [failed, setFailed] = useState(false);
  const active = useRef<AbortController | null>(null);
  useEffect(() => () => active.current?.abort(), []);
  const target = { kind: source.kind, accountId: account.accountId,
    recordId: source.kind === "TRADE" ? source.record.tradeId : source.record.cashFlowId };
  const name = source.kind === "TRADE" ? "交易" : "资金流水";
  const disabled = !session.canSave || checking || source.record.status !== "ACTIVE";
  const shown = [...errors, ...session.fieldErrors];
  async function preview() {
    if (disabled) return;
    const checked = validateEntryDraft(draft); setErrors(checked.errors); setFailed(false);
    if (!checked.input) return;
    const input = { ...checked.input, expectedRevision: source.record.revision };
    const controller = new AbortController(); active.current = controller; setChecking(true);
    try {
      const path = accountPath(account.accountId) + `/${source.kind === "TRADE" ? "trades" : "cash-flows"}/${target.recordId}/correction-preview`;
      const result = source.kind === "TRADE"
        ? await request(path, "TradeCorrectionPreview", { method: "POST", body: input, signal: controller.signal })
        : await request(path, "CashCorrectionPreview", { method: "POST", body: input, signal: controller.signal });
      if (controller.signal.aborted) return;
      if (result.expectedRevision !== source.record.revision) throw new Error("Preview revision mismatch");
      setErrors(result.fieldErrors);
      if (!result.fieldErrors.length) setReview({ input, preview: result });
    } catch (error) {
      if (!controller.signal.aborted) {
        if (error instanceof TradingAssistantApiError) setErrors(error.details.fieldErrors);
        setFailed(true);
      }
    } finally { if (!controller.signal.aborted) setChecking(false); }
  }
  if (action === "VOID") return <TradingAssistantDialog variant="fees" title={`作废${name}`} subtitle="作废不是删除，原始记录与作废痕迹保留" onClose={onClose}
    footer={<><TradingAssistantAction onClick={onClose}>取消</TradingAssistantAction>
      <TradingAssistantAction danger disabled={disabled} onClick={() => void session.save(source.kind === "TRADE" ? "TRADE_VOID" : "CASH_FLOW_VOID",
        { expectedRevision: source.record.revision }, target)}>确认作废</TradingAssistantAction></>}>
    <div className="ta-recovery-summary">{account.name} · {recordDraft(source).date}</div>
    <div className="ta-recovery-summary">{source.kind === "TRADE" ? `${source.record.stockRef.name} · ${source.record.direction === "BUY" ? "买入" : "卖出"} ${source.record.quantity} 股 · 成交价 ${source.record.price}`
      : `${source.record.direction === "IN" ? "转入" : "转出"} ${source.record.amount}`}<br />现金变动 {source.record.netCashChange}</div>
    <p className="ta-note">作废后该记录不再参与核算，将重新检查后续现金和可卖数量；若有冲突，不会保存。作废不能撤销。</p>
    {shown.map((error, i) => <p key={i} role="alert" className="ta-field-error">{error.message}</p>)}
  </TradingAssistantDialog>;
  return <>
    <TradingAssistantDialog variant="fees" title={`更正${name}`} subtitle={source.kind === "TRADE" ? "更正原始成交；闭环结果由系统重新计算" : "只更正入账 / 出账，不产生交易收益"} onClose={onClose}
      footer={<><TradingAssistantAction onClick={onClose}>取消</TradingAssistantAction>
        <TradingAssistantAction primary disabled={disabled} onClick={() => void preview()}>{checking ? "核对中…" : "核对更正"}</TradingAssistantAction></>}>
      <TradingAssistantField label="账户 · 只读" value={account.name} readOnly />
      {source.kind === "TRADE" && <div className="ta-segments" role="group" aria-label="交易方向">
        {(["BUY", "SELL"] as const).map(direction => <button key={direction} disabled={disabled} aria-pressed={draft.direction === direction}
          onClick={() => setDraft({ ...draft, direction })}>{direction === "BUY" ? "买入" : "卖出"}</button>)}
      </div>}
      <EntryFields draft={draft} onChange={setDraft} disabled={disabled} errors={shown} initializedOn={account.initializedOn} />
      <TradingAssistantField label="备注（选填）" value={draft.note} disabled={disabled} error={shown.find(e => e.field === "note")?.message}
        onChange={e => setDraft({ ...draft, note: e.target.value })} />
      <p className="ta-note">{source.kind === "TRADE" ? "按原税费配置自动计算；佣金和印花税不可手改。" : "保存前检查当前及受影响历史日期的现金余额。"}</p>
      {failed && <p role="alert" className="ta-form-error">暂时无法核对更正，请重试；当前填写内容仍保留。</p>}
    </TradingAssistantDialog>
    {review && (!session.recovery || session.editing) && <TradingAssistantDialog variant="fees" title={`确认${name}更正`} subtitle="请核对发生变化的内容" onClose={() => setReview(null)}
      footer={<><TradingAssistantAction onClick={() => setReview(null)}>返回修改</TradingAssistantAction>
        <TradingAssistantAction primary disabled={!session.canSave} onClick={() => void session.save(source.kind === "TRADE" ? "TRADE_CORRECT" : "CASH_FLOW_CORRECT", review.input, target)}>确认更正</TradingAssistantAction></>}>
      <div className="ta-recovery-summary">{account.name}</div>
      <dl className="ta-change-comparison">{comparisonFields(review.preview).map(([label, before, after]) => <div key={label} className="ta-change-row">
        <dt>{label}</dt><dd>{before === after ? `${before}（未变）` : `${before} → ${after}`}</dd>
      </div>)}</dl>
      <p className="ta-note">将从 {review.preview.affectedFromDate} 起重新计算现金、持仓、闭环交易及每日账户快照。重算完成前，相关收益不展示为可用结果。</p>
    </TradingAssistantDialog>}
  </>;
}
function comparisonFields(result: TradeCorrectionPreview | CashCorrectionPreview): string[][] {
  const before = result.before, after = result.after;
  const fields = "price" in before ? ["tsCode", "direction", "tradeDate", "price", "quantity", "grossAmount", "commissionAmount", "stampTaxAmount", "netCashChange", "note"]
    : ["direction", "occurredOn", "amount", "netCashChange", "note"];
  const labels: Record<string, string> = { tsCode: "股票", direction: "方向", tradeDate: "成交日期", occurredOn: "发生日期", price: "成交价格", quantity: "成交数量",
    grossAmount: "成交金额", commissionAmount: "自动佣金", stampTaxAmount: "印花税", netCashChange: "现金变动", amount: "金额", note: "备注" };
  const display = (value: unknown) => ({ BUY: "买入", SELL: "卖出", IN: "转入", OUT: "转出" }[String(value)] ?? String(value === "" ? "—" : value ?? "—"));
  return fields.map(field => [labels[field], display(before[field as keyof typeof before]), display(after[field as keyof typeof after])]);
}
