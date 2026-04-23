import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement } from "react";
import type { PropsWithChildren } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiRequest } from "../../shared/api/client";
import { buildTradeCalendarRange, createTradingDayResolver, useTradeCalendarField } from "./use-trade-calendar";

vi.mock("../../shared/api/client", () => ({
  apiRequest: vi.fn(),
}));

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  return function Wrapper({ children }: PropsWithChildren) {
    return createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

beforeEach(() => {
  vi.mocked(apiRequest).mockReset();
  vi.mocked(apiRequest).mockResolvedValue({ items: [] });
});

describe("useTradeCalendar helpers", () => {
  it("builds a buffered month range around the current calendar month", () => {
    expect(buildTradeCalendarRange("2026-04-20")).toEqual({
      calendarDate: "2026-04-20",
      startDate: "2026-03-25",
      endDate: "2026-05-07",
    });
  });

  it("resolves open and closed trade dates from server rows", () => {
    const resolver = createTradingDayResolver([
      { trade_date: "2026-04-20", is_open: true, pretrade_date: "2026-04-17" },
      { trade_date: "2026-04-21", is_open: false, pretrade_date: "2026-04-20" },
    ]);

    expect(resolver("2026-04-20")).toBe(true);
    expect(resolver("2026-04-21")).toBe(false);
    expect(resolver("2026-05-01")).toBeUndefined();
  });

  it("keeps the controlled calendar date in sync for year and decade navigation", () => {
    const { result } = renderHook(() => useTradeCalendarField({ value: "2026-04-20" }), {
      wrapper: createWrapper(),
    });

    expect(result.current.calendarDate).toBe("2026-04-20");

    act(() => {
      result.current.calendarProps.onYearSelect?.("2025-04-20");
    });
    expect(result.current.calendarDate).toBe("2025-04-20");

    act(() => {
      result.current.calendarProps.onNextYear?.("2026-04-20");
    });
    expect(result.current.calendarDate).toBe("2026-04-20");

    act(() => {
      result.current.calendarProps.onPreviousDecade?.("2016-04-20");
    });
    expect(result.current.calendarDate).toBe("2016-04-20");

    act(() => {
      result.current.calendarProps.onMonthSelect?.("2016-11-20");
    });
    expect(result.current.calendarDate).toBe("2016-11-20");
  });
});
