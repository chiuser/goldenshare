import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TurnoverInsightPanelViewModel } from "../model/turnoverInsightTypes";
import { TurnoverInsightPanel } from "./TurnoverInsightPanel";

const readyModel: TurnoverInsightPanelViewModel = {
  status: "READY",
  summary: {
    current: { amountYi: 1, displayText: "1亿", direction: "neutral" },
    previous: { amountYi: 2, displayText: "2亿", direction: "neutral" },
    delta: { amountYi: -1, displayText: "-1亿", direction: "down" },
    avg5d: { amountYi: 3, displayText: "3亿", direction: "neutral", referenceLabel: "5日均值 3亿" },
    avg20d: { amountYi: 4, displayText: "4亿", direction: "neutral", referenceLabel: "20日均值 4亿" },
  },
  upperAxis: { minYi: 0, maxYi: 4, zeroYi: 0, ticks: [{ valueYi: 0, displayText: "0" }] },
  deltaAxis: { minYi: -1, maxYi: 1, zeroYi: 0, ticks: [{ valueYi: 0, displayText: "0" }] },
  points: [{
    time: "09:30",
    showAxisLabel: true,
    currentAmountYi: 1,
    currentDisplayText: "1亿",
    previousAmountYi: 2,
    previousDisplayText: "2亿",
    deltaAmountYi: -1,
    deltaDisplayText: "-1亿",
    deltaDirection: "down",
  }],
  message: null,
  exceptionCode: null,
};

describe("TurnoverInsightPanel", () => {
  it.each(["full", "compact"] as const)("renders one shared %s chart shell", (layout) => {
    const { container } = render(
      <TurnoverInsightPanel layout={layout} model={readyModel} onRetry={vi.fn()} viewState="ready" />,
    );

    expect(container.querySelector(`.turnover-insight-panel--${layout}`)).toBeInTheDocument();
    expect(container.querySelectorAll("canvas")).toHaveLength(1);
    expect(screen.getByText("1亿")).toBeInTheDocument();
  });

  it("keeps loading and error states free of stale canvas content", () => {
    const retry = vi.fn();
    const { container, rerender } = render(
      <TurnoverInsightPanel layout="compact" model={null} onRetry={retry} viewState="loading" />,
    );
    expect(container.querySelector("canvas")).toBeNull();

    rerender(
      <TurnoverInsightPanel
        errorMessage="读取失败"
        layout="compact"
        model={null}
        onRetry={retry}
        viewState="error"
      />,
    );
    expect(container.querySelector("canvas")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
