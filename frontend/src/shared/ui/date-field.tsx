import { DatePickerInput } from "@mantine/dates";
import type { ComponentPropsWithoutRef } from "react";

export type DateSelectionRule = "any" | "week_friday" | "month_end";
type ExcludeDateInput = Parameters<NonNullable<ComponentPropsWithoutRef<typeof DatePickerInput>["excludeDate"]>>[0];

type DateFieldProps = Omit<ComponentPropsWithoutRef<typeof DatePickerInput>, "value" | "onChange" | "type" | "excludeDate"> & {
  value: string;
  onChange: (value: string) => void;
  selectionRule?: DateSelectionRule;
  excludeDate?: (value: ExcludeDateInput) => boolean;
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

function normalizeDateInput(value: ExcludeDateInput): string {
  const dateValue = value as unknown;
  if (dateValue instanceof Date) {
    return toDateString(dateValue);
  }
  return String(value || "");
}

export function isCalendarDateExcluded(value: ExcludeDateInput, selectionRule: DateSelectionRule = "any") {
  const parsed = parseInputDate(normalizeDateInput(value));
  if (!parsed) {
    return false;
  }
  if (selectionRule === "week_friday") {
    return parsed.getDay() !== 5;
  }
  if (selectionRule === "month_end") {
    const monthLastDay = new Date(parsed.getFullYear(), parsed.getMonth() + 1, 0).getDate();
    return parsed.getDate() !== monthLastDay;
  }
  return false;
}

export function DateField({ value, onChange, selectionRule = "any", excludeDate, ...props }: DateFieldProps) {
  const parsed = toDateString(parseInputDate(value));
  const pickerValue: string | null = parsed || null;
  const placeholder = props.placeholder || "请选择日期";
  const mergedExcludeDate = (candidate: ExcludeDateInput) =>
    isCalendarDateExcluded(candidate, selectionRule) || Boolean(excludeDate?.(candidate));

  return (
    <DatePickerInput
      {...props}
      value={pickerValue}
      placeholder={placeholder}
      excludeDate={mergedExcludeDate}
      onChange={(next) => onChange(normalizePickerValue(next))}
      valueFormat="YYYY-MM-DD"
      clearable
    />
  );
}
