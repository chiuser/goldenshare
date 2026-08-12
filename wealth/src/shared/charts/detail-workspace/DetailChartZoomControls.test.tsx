import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DetailChartZoomControls } from "./DetailChartZoomControls";

describe("DetailChartZoomControls", () => {
  it("renders the approved out-then-in buttons and exported Figma SVG geometry", () => {
    render(
      <DetailChartZoomControls
        canZoomIn
        canZoomOut
        onZoomIn={vi.fn()}
        onZoomOut={vi.fn()}
      />,
    );

    const group = screen.getByRole("group", { name: "K线缩放" });
    const buttons = group.querySelectorAll("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveAccessibleName("缩小K线，增加可见根数");
    expect(buttons[1]).toHaveAccessibleName("放大K线，减少可见根数");
    buttons.forEach((button) => {
      const svg = button.querySelector("svg");
      expect(svg).toHaveAttribute("viewBox", "0 0 16 16");
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(svg).toHaveAttribute("focusable", "false");
      expect(svg?.querySelector("path")).toHaveAttribute("transform", "translate(1.48618555 1.48618555)");
    });
  });

  it("uses native disabled semantics and only calls enabled actions", () => {
    const onZoomIn = vi.fn();
    const onZoomOut = vi.fn();
    render(
      <DetailChartZoomControls
        canZoomIn={false}
        canZoomOut
        onZoomIn={onZoomIn}
        onZoomOut={onZoomOut}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "缩小K线，增加可见根数" }));
    fireEvent.click(screen.getByRole("button", { name: "放大K线，减少可见根数" }));
    expect(onZoomOut).toHaveBeenCalledTimes(1);
    expect(onZoomIn).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "放大K线，减少可见根数" })).toBeDisabled();
  });
});
