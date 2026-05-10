import { describe, expect, it } from "vitest";

import { CALENDAR_WEEK_FRIDAY_SELECTION_RULE, isCalendarDateExcluded } from "./date-field";

describe("DateField calendar selection rules", () => {
  it("allows only natural Fridays for the stock weekly natural anchor rule", () => {
    expect(isCalendarDateExcluded("2026-04-23", CALENDAR_WEEK_FRIDAY_SELECTION_RULE)).toBe(true);
    expect(isCalendarDateExcluded("2026-04-24", CALENDAR_WEEK_FRIDAY_SELECTION_RULE)).toBe(false);
  });

  it("allows only natural month-end dates for month_end rule", () => {
    expect(isCalendarDateExcluded("2026-04-29", "month_end")).toBe(true);
    expect(isCalendarDateExcluded("2026-04-30", "month_end")).toBe(false);
    expect(isCalendarDateExcluded("2026-01-31", "month_end")).toBe(false);
  });
});
