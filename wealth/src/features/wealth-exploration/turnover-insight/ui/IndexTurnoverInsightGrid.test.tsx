import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  IndexTurnoverInsightControllerResult,
  IndexTurnoverInsightPanelViewModel,
} from "../model/indexTurnoverInsightTypes";
import { IndexTurnoverInsightGrid } from "./IndexTurnoverInsightGrid";

const NAMES = [
  "上证指数", "深证成指", "创业板", "科创50", "科创综指",
  "中证500", "中证A500", "沪深300", "中证1000", "上证50",
];

function panel(index: number): IndexTurnoverInsightPanelViewModel {
  const amount = { amountYi: 100 + index, displayText: `${100 + index}亿`, direction: "neutral" as const };
  return {
    tsCode: `${String(index).padStart(6, "0")}.SH`,
    indexName: NAMES[index]!,
    status: "READY",
    summary: {
      current: amount,
      previous: amount,
      delta: { ...amount, direction: "flat" },
      avg5d: { ...amount, referenceLabel: `5日均值 ${amount.displayText}` },
      avg20d: { ...amount, referenceLabel: `20日均值 ${amount.displayText}` },
    },
    upperAxis: { minYi: 0, maxYi: 200, zeroYi: 0, ticks: [] },
    deltaAxis: { minYi: -1, maxYi: 1, zeroYi: 0, ticks: [] },
    points: [{
      time: "09:30",
      showAxisLabel: true,
      currentAmountYi: 1,
      currentDisplayText: "1亿",
      previousAmountYi: 1,
      previousDisplayText: "1亿",
      deltaAmountYi: 0,
      deltaDisplayText: "0亿",
      deltaDirection: "flat",
    }],
    message: null,
    exceptionCode: null,
  };
}

function controller(overrides: Partial<IndexTurnoverInsightControllerResult> = {}): IndexTurnoverInsightControllerResult {
  return {
    capabilityState: "supported",
    viewState: "ready",
    model: {
      status: "READY",
      tradingDay: {
        expectedTradeDate: "2026-09-01",
        observedTradeDate: "2026-09-01",
        previousObservedTradeDate: "2026-08-31",
      },
      asOf: "盘后数据 · 2026-09-01",
      indices: Array.from({ length: 10 }, (_, index) => panel(index)),
      message: null,
      exceptionCode: null,
    },
    errorMessage: null,
    retry: vi.fn(),
    ...overrides,
  };
}

describe("IndexTurnoverInsightGrid", () => {
  it("renders the backend order as ten independent compact canvases", () => {
    const { container } = render(<IndexTurnoverInsightGrid controller={controller()} />);

    expect(Array.from(
      container.querySelectorAll(".index-turnover-insight-card__header h3"),
      (element) => element.textContent,
    )).toEqual(NAMES.map((name) => `${name}成交额`));
    expect(container.querySelectorAll(".index-turnover-insight-card")).toHaveLength(10);
    expect(container.querySelectorAll("canvas")).toHaveLength(10);
    expect(container.querySelectorAll(".turnover-insight-summary--compact")).toHaveLength(10);
    expect(container.querySelectorAll(".index-turnover-insight-card__asof")).toHaveLength(10);
    expect(container.querySelectorAll(".index-turnover-insight-card__identity small")).toHaveLength(10);
  });

  it("renders ten anonymous loading shells without inventing index identities", () => {
    const { container } = render(<IndexTurnoverInsightGrid controller={controller({
      capabilityState: "loading",
      viewState: "loading",
      model: null,
    })} />);

    expect(screen.getByLabelText("主要指数成交额加载中")).toBeInTheDocument();
    expect(container.querySelectorAll(".index-turnover-insight-card")).toHaveLength(10);
    expect(container.querySelectorAll(".index-turnover-insight-card__header h3")).toHaveLength(0);
    expect(container.querySelectorAll("canvas")).toHaveLength(0);
  });

  it("renders nothing only for unsupported endpoint capability", () => {
    const { container } = render(<IndexTurnoverInsightGrid controller={controller({
      capabilityState: "unsupported",
      model: null,
    })} />);
    expect(container).toBeEmptyDOMElement();
  });
});
