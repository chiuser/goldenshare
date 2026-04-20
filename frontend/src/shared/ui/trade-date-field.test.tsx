import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { TradeDateField, isTradeDateExcluded } from "./trade-date-field";

describe("TradeDateField", () => {
  it("uses trade-date specific placeholder", () => {
    render(
      <MantineProvider theme={appTheme}>
        <TradeDateField label="同步日期" value="" onChange={() => undefined} />
      </MantineProvider>,
    );

    expect(screen.getByRole("button", { name: "同步日期" })).toHaveTextContent("请选择交易日");
  });

  it("excludes weekends and configured holidays", () => {
    expect(isTradeDateExcluded("2026-04-18")).toBe(true);
    expect(isTradeDateExcluded("2026-04-20")).toBe(false);
    expect(isTradeDateExcluded("2026-04-21", ["2026-04-21"])).toBe(true);
  });

  it("prefers injected trading-day resolver when real calendar data is available", () => {
    const isTradingDay = (date: string) => {
      if (date === "2026-04-18") return true;
      if (date === "2026-04-21") return false;
      return undefined;
    };

    expect(isTradeDateExcluded("2026-04-18", [], isTradingDay)).toBe(false);
    expect(isTradeDateExcluded("2026-04-21", [], isTradingDay)).toBe(true);
    expect(isTradeDateExcluded("2026-04-19", [], isTradingDay)).toBe(true);
  });

  it("only allows the last trading day of each week for weekly anchor resources", () => {
    const isTradingDay = (date: string) => {
      const closedDates = new Set(["2026-04-30", "2026-05-01", "2026-05-02", "2026-05-03"]);
      const knownDates = new Set(["2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30", "2026-05-01", "2026-05-02", "2026-05-03"]);
      if (closedDates.has(date)) {
        return false;
      }
      if (knownDates.has(date)) {
        return true;
      }
      return undefined;
    };

    expect(isTradeDateExcluded("2026-04-28", [], isTradingDay, "week_last_trading_day")).toBe(true);
    expect(isTradeDateExcluded("2026-04-29", [], isTradingDay, "week_last_trading_day")).toBe(false);
  });

  it("only allows the last trading day of each month for monthly anchor resources", () => {
    const isTradingDay = (date: string) => {
      const closedDates = new Set(["2026-01-31", "2026-02-01"]);
      const knownDates = new Set(["2026-01-29", "2026-01-30", "2026-01-31", "2026-02-01"]);
      if (closedDates.has(date)) {
        return false;
      }
      if (knownDates.has(date)) {
        return true;
      }
      return undefined;
    };

    expect(isTradeDateExcluded("2026-01-29", [], isTradingDay, "month_end")).toBe(true);
    expect(isTradeDateExcluded("2026-01-30", [], isTradingDay, "month_end")).toBe(false);
    expect(isTradeDateExcluded("2026-01-31", [], isTradingDay, "month_end")).toBe(true);
  });
});
