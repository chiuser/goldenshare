import { describe, expect, it } from "vitest";

import { buildTradeCalendarRange, createTradingDayResolver } from "./use-trade-calendar";

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
});
