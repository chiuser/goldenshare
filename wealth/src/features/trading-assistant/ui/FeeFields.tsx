import type { FeeInputs, FieldErrorDto } from "../api/generatedContracts";
import { TradingAssistantField } from "./TradingAssistantForm";

export function FeeFields({ value, onChange, errors = [], disabled = false }: {
  value: FeeInputs; onChange: (value: FeeInputs) => void; errors?: FieldErrorDto[]; disabled?: boolean;
}) {
  return <>
    <TradingAssistantField required label="交易佣金率（万分之）" inputMode="decimal" value={value.commissionRateWan} disabled={disabled}
      error={errors.find(error => error.field === "commissionRateWan")?.message}
      onChange={event => onChange({ ...value, commissionRateWan: event.target.value })} />
    <TradingAssistantField required label="单笔最低佣金（元）" inputMode="decimal" value={value.minimumCommission} disabled={disabled}
      error={errors.find(error => error.field === "minimumCommission")?.message}
      onChange={event => onChange({ ...value, minimumCommission: event.target.value })} />
    <TradingAssistantField required label="卖出印花税率（%）" inputMode="decimal" value={value.stampTaxRatePct} disabled={disabled}
      error={errors.find(error => error.field === "stampTaxRatePct")?.message}
      onChange={event => onChange({ ...value, stampTaxRatePct: event.target.value })} />
    <div className="ta-notice">新交易与当前卖出估算使用当前费率。历史费用、历史快照不变；买入不收印花税。</div>
  </>;
}
