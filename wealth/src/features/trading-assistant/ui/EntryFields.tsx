import type { FieldErrorDto } from "../api/generatedContracts";
import type { EntryDraft } from "../model/entryDraft";
import { TradingAssistantField } from "./TradingAssistantForm";
import { TradingAssistantStockPicker } from "./TradingAssistantStockPicker";

export function EntryFields({ draft, onChange, disabled, errors, initializedOn }: {
  draft: EntryDraft; onChange: (draft: EntryDraft) => void; disabled: boolean; errors: FieldErrorDto[]; initializedOn: string;
}) {
  const errorFor = (field: string) => errors.find(error => error.field === field)?.message;
  return <>
    {draft.kind === "CASH" ? <div className="ta-segments" role="group" aria-label="资金方向">
      {(["IN", "OUT"] as const).map(direction => <button key={direction} type="button" disabled={disabled}
        aria-pressed={draft.direction === direction} onClick={() => onChange({ ...draft, direction })}>{direction === "IN" ? "资金转入" : "资金转出"}</button>)}
    </div> : <>
      <div className="ta-notice"><strong>按日期记录，系统执行 A 股 T+1 校验</strong>佣金和印花税自动计算、不可手改；新费率不影响旧交易。</div>
      <TradingAssistantStockPicker value={draft.stock} disabled={disabled} error={errorFor("tsCode")} onChange={stock => onChange({ ...draft, stock })} />
    </>}
    <TradingAssistantField required label={draft.kind === "TRADE" ? "成交日期" : "发生日期"} type="date" min={initializedOn}
      value={draft.date} disabled={disabled} error={errorFor(draft.kind === "TRADE" ? "tradeDate" : "occurredOn")}
      onChange={event => onChange({ ...draft, date: event.target.value })} />
    {draft.kind === "TRADE" ? <>
      <TradingAssistantField required label="成交价格（元）" inputMode="decimal" value={draft.price} disabled={disabled}
        error={errorFor("price")} onChange={event => onChange({ ...draft, price: event.target.value })} />
      <TradingAssistantField required label="成交数量（股）" inputMode="numeric" value={draft.quantity} disabled={disabled}
        error={errorFor("quantity")} onChange={event => onChange({ ...draft, quantity: event.target.value })} />
    </> : <TradingAssistantField required label="金额（元）" inputMode="decimal" value={draft.amount} disabled={disabled}
      error={errorFor("amount")} onChange={event => onChange({ ...draft, amount: event.target.value })} />}
  </>;
}
