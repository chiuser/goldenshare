import { MantineProvider } from "@mantine/core";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appTheme } from "../../app/theme";
import { MetricPanel } from "./metric-panel";

describe("MetricPanel", () => {
  it("renders label and metric content", () => {
    render(
      <MantineProvider theme={appTheme}>
        <MetricPanel label="今日执行次数">
          <span>12</span>
        </MetricPanel>
      </MantineProvider>,
    );

    expect(screen.getByText("今日执行次数")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
  });
});
