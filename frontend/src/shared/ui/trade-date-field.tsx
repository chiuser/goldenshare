import { DatePickerInput } from "@mantine/dates";
import type { ComponentPropsWithoutRef } from "react";

import { DateField, type DateSelectionRule } from "./date-field";

type ExcludeDateInput = Parameters<NonNullable<ComponentPropsWithoutRef<typeof DatePickerInput>["excludeDate"]>>[0];

interface TradeDateFieldProps extends Omit<ComponentPropsWithoutRef<typeof DateField>, "selectionRule"> {
  holidayDates?: string[];
  selectionRule?: DateSelectionRule;
}

function normalizeTradeDateInput(value: ExcludeDateInput): string {
  const dateValue = value as unknown;
  if (dateValue instanceof Date) {
    const year = dateValue.getFullYear();
    const month = String(dateValue.getMonth() + 1).padStart(2, "0");
    const day = String(dateValue.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }
  return String(value || "");
}

export function isTradeDateExcluded(value: ExcludeDateInput, holidayDates: string[] = []) {
  const normalized = normalizeTradeDateInput(value);
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) {
    return false;
  }
  const day = parsed.getDay();
  if (day === 0 || day === 6) {
    return true;
  }
  return holidayDates.includes(normalized);
}

export function TradeDateField({
  holidayDates = [],
  placeholder = "请选择交易日",
  selectionRule = "any",
  ...props
}: TradeDateFieldProps) {
  return (
    <DateField
      {...props}
      placeholder={placeholder}
      selectionRule={selectionRule}
      excludeDate={(value) => isTradeDateExcluded(value, holidayDates)}
    />
  );
}
