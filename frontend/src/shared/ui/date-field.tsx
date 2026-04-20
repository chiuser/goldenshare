import { DatePickerInput } from "@mantine/dates";
import type { ComponentPropsWithoutRef } from "react";

export type DateSelectionRule = "any" | "week_last_trading_day" | "month_end";

type DateFieldProps = Omit<ComponentPropsWithoutRef<typeof DatePickerInput>, "value" | "onChange" | "type"> & {
  value: string;
  onChange: (value: string) => void;
};

function parseInputDate(value: string): Date | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const [yearRaw, monthRaw, dayRaw] = trimmed.split("-");
  const year = Number(yearRaw);
  const month = Number(monthRaw);
  const day = Number(dayRaw);
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
    return null;
  }
  const parsed = new Date(year, month - 1, day);
  if (parsed.getFullYear() !== year || parsed.getMonth() !== month - 1 || parsed.getDate() !== day) {
    return null;
  }
  return parsed;
}

function normalizePickerValue(
  value: string | string[] | [string | null, string | null] | null,
): string {
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    const first = value[0];
    return typeof first === "string" ? first : "";
  }
  return "";
}

function toDateString(value: Date | null): string {
  if (!value) {
    return "";
  }
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function DateField({ value, onChange, ...props }: DateFieldProps) {
  const parsed = toDateString(parseInputDate(value));
  const pickerValue: string | null = parsed || null;
  const placeholder = props.placeholder || "请选择日期";

  return (
    <DatePickerInput
      {...props}
      value={pickerValue}
      placeholder={placeholder}
      onChange={(next) => onChange(normalizePickerValue(next))}
      valueFormat="YYYY-MM-DD"
      clearable
    />
  );
}
