import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { PriceText } from "./price-text";

describe("PriceText", () => {
  it("formats numeric values with fixed digits", () => {
    render(
      <MantineProvider theme={appTheme}>
        <PriceText value="62.48" />
      </MantineProvider>,
    );

    expect(screen.getByText("62.48")).toBeInTheDocument();
  });

  it("renders placeholder for empty values", () => {
    render(
      <MantineProvider theme={appTheme}>
        <PriceText value={null} />
      </MantineProvider>,
    );

    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
