import type { CashFlowInput, FieldErrorDto, StockRef, TradeInput } from "../api/generatedContracts";
import { validInputField } from "../api/contractValidation";

export type EntryDraft = { kind: "TRADE" | "CASH"; direction: "BUY" | "SELL" | "IN" | "OUT";
  stock: StockRef | null; date: string; price: string; quantity: string; amount: string; note: string; noteWasNull?: boolean };
export function validateEntryDraft(draft: EntryDraft): { input: TradeInput | CashFlowInput | null; errors: FieldErrorDto[] } {
  const errors: FieldErrorDto[] = [];
  const invalid = (field: string, message = "请检查必填项、格式和取值范围") => errors.push({ field, message, clientRowId: null, affectedOn: null });
  if (draft.kind === "CASH") {
    const input = { direction: draft.direction, occurredOn: draft.date, amount: draft.amount, note: draft.noteWasNull && !draft.note ? null : draft.note };
    for (const [field, value] of Object.entries(input)) if (!validInputField("CashFlowInput", field, value)) invalid(field);
    return { input: errors.length ? null : input as CashFlowInput, errors };
  }
  if (!draft.stock) invalid("tsCode", "请选择股票");
  if (!/^[0-9]+$/.test(draft.quantity)) invalid("quantity");
  const input = { direction: draft.direction, tradeDate: draft.date, tsCode: draft.stock?.tsCode ?? "",
    price: draft.price, quantity: Number(draft.quantity), note: draft.noteWasNull && !draft.note ? null : draft.note };
  for (const [field, value] of Object.entries(input)) if (!validInputField("TradeInput", field, value) && !errors.some(e => e.field === field)) invalid(field);
  return { input: errors.length ? null : input as TradeInput, errors };
}

export function beijingInputDate(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(now);
  const part = (type: string) => parts.find(item => item.type === type)!.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function formatBeijingInstant(value: string): string {
  return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(value));
}
