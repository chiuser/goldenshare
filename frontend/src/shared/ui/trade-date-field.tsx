import { DatePickerInput } from "@mantine/dates";
import type { ComponentPropsWithoutRef } from "react";

import { DateField } from "./date-field";

type ExcludeDateInput = Parameters<NonNullable<ComponentPropsWithoutRef<typeof DatePickerInput>["excludeDate"]>>[0];
export type TradeDateSelectionRule = "any" | "week_last_trading_day" | "month_end";

interface TradeDateFieldProps extends Omit<ComponentPropsWithoutRef<typeof DateField>, "selectionRule"> {
  holidayDates?: string[];
  isTradingDay?: (date: string) => boolean | undefined;
  selectionRule?: TradeDateSelectionRule;
}

function parseTradeDate(value: string): Date | null {
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

function formatTradeDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(value: Date, days: number): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate() + days);
}

function getIsoWeekKey(value: Date): string {
  const normalized = new Date(value.getFullYear(), value.getMonth(), value.getDate());
  const weekday = (normalized.getDay() + 6) % 7;
  normalized.setDate(normalized.getDate() - weekday + 3);

  const firstThursday = new Date(normalized.getFullYear(), 0, 4);
  const firstWeekday = (firstThursday.getDay() + 6) % 7;
  firstThursday.setDate(firstThursday.getDate() - firstWeekday + 3);

  const diff = normalized.getTime() - firstThursday.getTime();
  const week = 1 + Math.round(diff / 604800000);
  return `${normalized.getFullYear()}-${String(week).padStart(2, "0")}`;
}

function normalizeTradeDateInput(value: ExcludeDateInput): string {
  const dateValue = value as unknown;
  if (dateValue instanceof Date) {
    return formatTradeDate(dateValue);
  }
  return String(value || "");
}

function isKnownTradingDay(
  normalized: string,
  parsed: Date,
  holidayDates: string[],
  isTradingDay?: (date: string) => boolean | undefined,
): boolean {
  const resolvedTradingDay = isTradingDay?.(normalized);
  if (resolvedTradingDay !== undefined) {
    return resolvedTradingDay;
  }
  const day = parsed.getDay();
  if (day === 0 || day === 6) {
    return false;
  }
  return !holidayDates.includes(normalized);
}

function hasFutureTradingDayInSameCycle(
  parsed: Date,
  selectionRule: TradeDateSelectionRule,
  holidayDates: string[],
  isTradingDay?: (date: string) => boolean | undefined,
): boolean {
  const sameCycle = (candidate: Date) => {
    if (selectionRule === "week_last_trading_day") {
      return getIsoWeekKey(candidate) === getIsoWeekKey(parsed);
    }
    return candidate.getFullYear() === parsed.getFullYear() && candidate.getMonth() === parsed.getMonth();
  };

  let cursor = addDays(parsed, 1);
  while (sameCycle(cursor)) {
    const normalized = formatTradeDate(cursor);
    if (isKnownTradingDay(normalized, cursor, holidayDates, isTradingDay)) {
      return true;
    }
    cursor = addDays(cursor, 1);
  }
  return false;
}

export function isTradeDateExcluded(
  value: ExcludeDateInput,
  holidayDates: string[] = [],
  isTradingDay?: (date: string) => boolean | undefined,
  selectionRule: TradeDateSelectionRule = "any",
) {
  const normalized = normalizeTradeDateInput(value);
  const parsed = parseTradeDate(normalized);
  if (!parsed) {
    return false;
  }

  if (!isKnownTradingDay(normalized, parsed, holidayDates, isTradingDay)) {
    return true;
  }

  if (selectionRule === "any") {
    return false;
  }

  return hasFutureTradingDayInSameCycle(parsed, selectionRule, holidayDates, isTradingDay);
}

export function TradeDateField({
  holidayDates = [],
  isTradingDay,
  placeholder = "请选择交易日",
  selectionRule = "any",
  ...props
}: TradeDateFieldProps) {
  return (
    <DateField
      {...props}
      placeholder={placeholder}
      excludeDate={(value) => isTradeDateExcluded(value, holidayDates, isTradingDay, selectionRule)}
    />
  );
}
