import type { FieldErrorDto, InitializationPositionInput, StockRef } from "../api/generatedContracts";
import { validInputField } from "../api/contractValidation";

export interface PositionDraft { clientRowId: string; stock: StockRef | null; openedOn: string; quantity: string; availableQuantity: string; costPrice: string }
export function positionDrafts(rows: InitializationPositionInput[]): PositionDraft[] {
  return rows.map(row => ({ clientRowId: row.clientRowId, stock: { tsCode: row.tsCode, name: "" },
    openedOn: row.openedOn, quantity: String(row.quantity), availableQuantity: String(row.availableQuantity), costPrice: row.costPrice }));
}
export function validateInitialPositions(rows: PositionDraft[], initializedOn?: string) {
  const errors: FieldErrorDto[] = [], values: InitializationPositionInput[] = [];
  for (const row of rows) {
    const invalid = (field: string, message = "请检查必填项、格式和取值范围") => errors.push({
      field: `initialPositions.${field}`, clientRowId: row.clientRowId, message, affectedOn: null });
    if (!row.stock) invalid("tsCode", "请选择股票");
    if (!row.openedOn) invalid("openedOn", "请选择建仓日期。");
    else if (!validInputField("InitializationPositionInput", "openedOn", row.openedOn)) invalid("openedOn", "请输入有效的建仓日期。");
    else if (initializedOn && row.openedOn > initializedOn) invalid("openedOn", "建仓日期不能晚于首次录入日期。");
    for (const field of ["quantity", "availableQuantity"] as const) {
      if (!/^[0-9]+$/.test(row[field]) || !validInputField("InitializationPositionInput", field, Number(row[field]))) invalid(field);
    }
    if (!validInputField("InitializationPositionInput", "costPrice", row.costPrice)) invalid("costPrice");
    if (/^[0-9]+$/.test(row.quantity) && /^[0-9]+$/.test(row.availableQuantity) && BigInt(row.availableQuantity) > BigInt(row.quantity))
      invalid("availableQuantity", "初始化当日可卖数量不能超过持仓数量");
    if (row.stock && values.some(previous => previous.tsCode === row.stock!.tsCode)) invalid("tsCode", "同一只股票请合并录入期初持仓");
    if (row.stock) values.push({ clientRowId: row.clientRowId, tsCode: row.stock.tsCode,
      openedOn: row.openedOn,
      quantity: Number(row.quantity), availableQuantity: Number(row.availableQuantity), costPrice: row.costPrice });
  }
  return { errors, values };
}
