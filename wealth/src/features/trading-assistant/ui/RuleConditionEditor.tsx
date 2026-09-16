import type { Conditions, FieldErrorDto } from "../api/generatedContracts";
import { TradingAssistantField } from "./TradingAssistantForm";
import { conditionText } from "../model/rulePresentation";
import "./trading-assistant-rules.css";

export function RuleConditionEditor({ value, onChange, disabled = false, errors = [] }: {
  value: Conditions; onChange: (value: Conditions) => void; disabled?: boolean; errors?: FieldErrorDto[];
}) {
  const price = value.priceCondition, volume = value.volumeCondition;
  const error = (field: string) => errors.find(e => e.field === field)?.message;
  return <fieldset className="ta-rule-conditions" disabled={disabled}>
    <label className="ta-rule-enable"><input type="checkbox" checked={price !== null} onChange={e => onChange({ ...value, priceCondition: e.target.checked ? { operator: "LTE", upper: "" } : null })} />价格条件</label>
    {price && <>
      <div className="ta-segments" role="group" aria-label="价格比较方式">{([['LTE','不高于 ≤'],['GTE','不低于 ≥'],['BETWEEN','区间（含边界）']] as const).map(([operator, label]) => <button type="button" key={operator} aria-pressed={price.operator === operator} onClick={() => {
        const lower = "lower" in price ? price.lower : "", upper = "upper" in price ? price.upper : "";
        onChange({ ...value, priceCondition: operator === "LTE" ? { operator, upper } : operator === "GTE" ? { operator, lower } : { operator, lower, upper } });
      }}>{label}</button>)}</div>
      <div className="ta-rule-price-fields">
        {"lower" in price && <TradingAssistantField label="价格下限（元）" inputMode="decimal" value={price.lower} error={error("priceCondition.lower")} onChange={e => onChange({ ...value, priceCondition: { ...price, lower: e.target.value } })} />}
        {"upper" in price && <TradingAssistantField label="价格上限（元）" inputMode="decimal" value={price.upper} error={error("priceCondition.upper")} onChange={e => onChange({ ...value, priceCondition: { ...price, upper: e.target.value } })} />}
      </div>
    </>}
    <label className="ta-rule-enable"><input type="checkbox" checked={volume !== null} onChange={e => onChange({ ...value, volumeCondition: e.target.checked ? { operator: "GTE", thresholdLots: "" } : null })} />当日累计成交量</label>
    {volume && <>
      <div className="ta-segments" role="group" aria-label="成交量比较方式">{([['GTE','不低于 ≥'],['LTE','不高于 ≤']] as const).map(([operator, label]) => <button key={operator} type="button" aria-pressed={volume.operator === operator} onClick={() => onChange({ ...value, volumeCondition: { ...volume, operator } })}>{label}</button>)}</div>
      <TradingAssistantField label="累计成交量（手）" inputMode="decimal" value={volume.thresholdLots} error={error("volumeCondition.thresholdLots")} onChange={e => onChange({ ...value, volumeCondition: { ...volume, thresholdLots: e.target.value } })} />
      <p className="ta-note">截至检查分钟，从当日开盘累计；不是单分钟量，也不是计划买卖数量。</p>
    </>}
    <p className="ta-note">按前复权分钟收盘价验证；全部启用条件须在同一完整分钟满足。</p>
    <p className="ta-rule-preview" aria-label="条件预览">{conditionText(value)}</p>
    {errors.filter(e => ['conditions', 'priceCondition', 'volumeCondition'].includes(e.field)).map(e => <p key={e.field} role="alert" className="ta-form-error">{e.message}</p>)}
  </fieldset>;
}
