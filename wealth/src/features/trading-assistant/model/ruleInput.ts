import type { Conditions, FieldErrorDto } from "../api/generatedContracts";
import { parseContract, validInputField } from "../api/contractValidation";

export function conditionErrors(value: Conditions): FieldErrorDto[] {
  const errors: FieldErrorDto[] = [];
  const add = (field: string, message: string) => errors.push({ field, message, clientRowId: null, affectedOn: null });
  const price = value.priceCondition, volume = value.volumeCondition;
  if (!price && !volume) add("conditions", "至少启用一项条件");
  if (price) {
    for (const field of ["lower", "upper"] as const) if (field in price && !validInputField(field === "lower" ? "PriceGTE" : "PriceLTE", field, price[field as keyof typeof price])) add(`priceCondition.${field}`, "请输入大于 0、最多两位小数的价格");
    if (!errors.length && price.operator === "BETWEEN") { try { parseContract("PriceBetween", price); } catch { add("priceCondition", "价格下限不能高于上限"); } }
  }
  if (volume && !validInputField("VolumeCondition", "thresholdLots", volume.thresholdLots)) add("volumeCondition.thresholdLots", "请输入大于 0、最多两位小数的累计成交量");
  return errors;
}
