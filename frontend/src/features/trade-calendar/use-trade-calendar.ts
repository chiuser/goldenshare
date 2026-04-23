import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { apiRequest } from "../../shared/api/client";
import type { MarketTradeCalendarItem, MarketTradeCalendarResponse } from "../../shared/api/calendar-types";

interface UseTradeCalendarFieldOptions {
  exchange?: string;
  value?: string;
}

type TradingDayResolver = (date: string) => boolean | undefined;

function parseDate(value: string): Date | null {
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

function formatDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(value: Date, days: number): Date {
  return new Date(value.getFullYear(), value.getMonth(), value.getDate() + days);
}

function getTodayString(): string {
  return formatDate(new Date());
}

function normalizeCalendarDate(value?: string): string {
  return parseDate(value || "") ? value!.trim() : getTodayString();
}

export function buildTradeCalendarRange(anchorDate: string): { calendarDate: string; startDate: string; endDate: string } {
  const normalizedDate = normalizeCalendarDate(anchorDate);
  const parsed = parseDate(normalizedDate) || parseDate(getTodayString())!;
  const monthStart = new Date(parsed.getFullYear(), parsed.getMonth(), 1);
  const monthEnd = new Date(parsed.getFullYear(), parsed.getMonth() + 1, 0);
  return {
    calendarDate: normalizedDate,
    startDate: formatDate(addDays(monthStart, -7)),
    endDate: formatDate(addDays(monthEnd, 7)),
  };
}

export function createTradingDayResolver(items: MarketTradeCalendarItem[]): TradingDayResolver {
  const tradingDayMap = new Map(items.map((item) => [item.trade_date, item.is_open]));
  return (date: string) => tradingDayMap.get(date);
}

export function useTradeCalendarField({ exchange = "SSE", value = "" }: UseTradeCalendarFieldOptions) {
  const [calendarDate, setCalendarDate] = useState(() => normalizeCalendarDate(value));

  useEffect(() => {
    if (!value) {
      return;
    }
    const normalized = normalizeCalendarDate(value);
    setCalendarDate((current) => (
      normalized.slice(0, 7) === current.slice(0, 7) ? current : normalized
    ));
  }, [value]);

  const range = useMemo(() => buildTradeCalendarRange(calendarDate), [calendarDate]);

  const calendarQuery = useQuery({
    queryKey: ["market", "trade-calendar", exchange, range.startDate, range.endDate],
    queryFn: () =>
      apiRequest<MarketTradeCalendarResponse>(
        `/api/v1/market/trade-calendar?exchange=${encodeURIComponent(exchange)}&start_date=${range.startDate}&end_date=${range.endDate}`,
      ),
    staleTime: 5 * 60 * 1000,
  });

  const isTradingDay = useMemo(
    () => createTradingDayResolver(calendarQuery.data?.items || []),
    [calendarQuery.data?.items],
  );

  const handleCalendarDateChange = (nextDate: string) => {
    setCalendarDate(normalizeCalendarDate(nextDate));
  };

  return {
    calendarDate: range.calendarDate,
    calendarQuery,
    calendarProps: {
      date: range.calendarDate,
      onDateChange: handleCalendarDateChange,
      onMonthSelect: handleCalendarDateChange,
      onYearSelect: handleCalendarDateChange,
      onNextMonth: handleCalendarDateChange,
      onPreviousMonth: handleCalendarDateChange,
      onNextYear: handleCalendarDateChange,
      onPreviousYear: handleCalendarDateChange,
      onNextDecade: handleCalendarDateChange,
      onPreviousDecade: handleCalendarDateChange,
    },
    isTradingDay,
  };
}
