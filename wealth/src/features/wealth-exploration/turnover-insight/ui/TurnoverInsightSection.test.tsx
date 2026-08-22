import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TurnoverInsightViewModel } from "../model/turnoverInsightTypes";
import { TurnoverInsightSection } from "./TurnoverInsightSection";

function model(status: TurnoverInsightViewModel["status"]): TurnoverInsightViewModel {
  const partial = status === "PARTIAL";
  return {
    status,
    tradingDay: {
      expectedTradeDate: "2026-08-21",
      observedTradeDate: "2026-08-21",
      previousObservedTradeDate: partial ? null : "2026-08-20",
    },
    asOf: "2026-08-22T09:15:00+08:00",
    summary: {
      current: { amountYi: 18921, displayText: "18,921亿", direction: "neutral" },
      previous: partial
        ? { amountYi: null, displayText: "--", direction: "neutral" }
        : { amountYi: 20939, displayText: "20,939亿", direction: "neutral" },
      delta: partial
        ? { amountYi: null, displayText: "--", direction: "neutral" }
        : { amountYi: -2018, displayText: "-2,018亿", direction: "down" },
      avg5d: {
        amountYi: 23771,
        displayText: "23,771亿",
        direction: "neutral",
        referenceLabel: "5日均值 23,771亿",
      },
      avg20d: {
        amountYi: 28064,
        displayText: "28,064亿",
        direction: "neutral",
        referenceLabel: "20日均值 28,064亿",
      },
    },
    upperAxis: { minYi: 0, maxYi: 24000, zeroYi: 0, ticks: [{ valueYi: 0, displayText: "0" }] },
    deltaAxis: partial ? null : { minYi: -2400, maxYi: 0, zeroYi: 0, ticks: [{ valueYi: 0, displayText: "0" }] },
    points: [{
      time: "09:30",
      showAxisLabel: true,
      currentAmountYi: 1,
      currentDisplayText: "1亿",
      previousAmountYi: partial ? null : 2,
      previousDisplayText: partial ? "--" : "2亿",
      deltaAmountYi: partial ? null : -1,
      deltaDisplayText: partial ? "--" : "-1亿",
      deltaDirection: partial ? "flat" : "down",
    }],
    message: partial ? "上一交易日数据暂不完整。" : null,
    exceptionCode: null,
  };
}

describe("TurnoverInsightSection", () => {
  it.each([
    ["ready", "READY"],
    ["delayed", "DELAYED"],
    ["partial", "PARTIAL"],
  ] as const)("renders the %s state through the same section", (viewState, status) => {
    const { container } = render(
      <TurnoverInsightSection model={model(status)} onRetry={vi.fn()} viewState={viewState} />,
    );
    expect(screen.getByText("成交额洞察")).toBeInTheDocument();
    expect(container.querySelectorAll("canvas")).toHaveLength(1);
  });

  it("renders loading without a canvas", () => {
    const { container } = render(
      <TurnoverInsightSection model={null} onRetry={vi.fn()} viewState="loading" />,
    );
    expect(screen.getByLabelText("成交额洞察加载中")).toBeInTheDocument();
    expect(container.querySelector("canvas")).toBeNull();
  });

  it("renders the five metric cards in the reviewed order", () => {
    const { container } = render(
      <TurnoverInsightSection model={model("READY")} onRetry={vi.fn()} viewState="ready" />,
    );

    const labels = Array.from(
      container.querySelectorAll(".turnover-insight-metric > span"),
      (element) => element.textContent,
    );
    expect(labels).toEqual([
      "当日累计成交额",
      "昨日累计成交额",
      "较昨日累计增减",
      "5日成交额均值",
      "20日成交额均值",
    ]);
    expect(screen.getByText("23,771亿")).toBeInTheDocument();
    expect(screen.getByText("28,064亿")).toBeInTheDocument();
  });

  it.each(["empty", "error"] as const)("renders %s without stale chart data", (viewState) => {
    const { container } = render(
      <TurnoverInsightSection model={null} onRetry={vi.fn()} viewState={viewState} />,
    );
    expect(container.querySelector("canvas")).toBeNull();
  });
});
