import type { FieldErrorDto } from "../api/generatedContracts";
import type { PositionDraft } from "../model/initialPositionDraft";
import { TradingAssistantAction, TradingAssistantField } from "./TradingAssistantForm";
import { TradingAssistantStockPicker } from "./TradingAssistantStockPicker";

export function InitialPositionFields({ rows, onChange, disabled, errors }: {
  rows: PositionDraft[]; onChange: (rows: PositionDraft[]) => void; disabled: boolean; errors: FieldErrorDto[];
}) {
  const errorFor = (field: string, row?: string) => errors.find(error => error.field === field && (error.clientRowId ?? undefined) === row)?.message;
  const change = (id: string, patch: Partial<PositionDraft>) => onChange(rows.map(row => row.clientRowId === id ? { ...row, ...patch } : row));
  return <>
    {rows.map(row => <section className="ta-initial-position" key={row.clientRowId} aria-label="期初持仓">
      <TradingAssistantStockPicker value={row.stock} disabled={disabled} error={errorFor("initialPositions.tsCode", row.clientRowId)}
        onChange={stock => change(row.clientRowId, { stock })} />
      <div className="ta-initial-numbers">
        <TradingAssistantField required label="持仓数量（股）" inputMode="numeric" value={row.quantity} disabled={disabled}
          error={errorFor("initialPositions.quantity", row.clientRowId)} onChange={event => change(row.clientRowId, { quantity: event.target.value })} />
        <TradingAssistantField required label="当日可卖数量（股）" inputMode="numeric" value={row.availableQuantity} disabled={disabled}
          error={errorFor("initialPositions.availableQuantity", row.clientRowId)} onChange={event => change(row.clientRowId, { availableQuantity: event.target.value })} />
        <TradingAssistantField required label="持仓成本价（元）" inputMode="decimal" value={row.costPrice} disabled={disabled}
          error={errorFor("initialPositions.costPrice", row.clientRowId)} onChange={event => change(row.clientRowId, { costPrice: event.target.value })} />
      </div>
      <p className="ta-note">成本价视为已包含买入费用；请填写初始化当日实际可卖数量，0 也是有效值。</p>
      <button type="button" className="ta-text-action" disabled={disabled} onClick={() => onChange(rows.filter(item => item.clientRowId !== row.clientRowId))}>移除该持仓</button>
    </section>)}
    <TradingAssistantAction disabled={disabled} onClick={() => onChange([...rows, {
      clientRowId: crypto.randomUUID(), stock: null, quantity: "", availableQuantity: "", costPrice: "",
    }])}>添加持仓股票</TradingAssistantAction>
    {errorFor("initialPositions") && <p className="ta-form-error" role="alert">{errorFor("initialPositions")}</p>}
  </>;
}
