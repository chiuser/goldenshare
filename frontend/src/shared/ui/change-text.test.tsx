import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { ChangeText } from "./change-text";

describe("ChangeText", () => {
  it("formats positive values with sign and suffix", () => {
    render(
      <MantineProvider theme={appTheme}>
        <ChangeText value="3.21" suffix="%" />
      </MantineProvider>,
    );

    expect(screen.getByText("+3.21%")).toBeInTheDocument();
  });

  it("renders negative values and neutral placeholder", () => {
    const { rerender } = render(
      <MantineProvider theme={appTheme}>
        <ChangeText value="-1.32" suffix="%" />
      </MantineProvider>,
    );

    expect(screen.getByText("-1.32%")).toBeInTheDocument();

    rerender(
      <MantineProvider theme={appTheme}>
        <ChangeText value={null} suffix="%" />
      </MantineProvider>,
    );

    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
