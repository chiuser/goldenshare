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
});
