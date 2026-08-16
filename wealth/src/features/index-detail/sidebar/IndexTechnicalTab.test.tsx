import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { NineTurnPeriod, NineTurnSeriesDto } from "../../nine-turn/api/nineTurnApiTypes";
import { idleNineTurnLayer, unsupportedNineTurnLayer } from "../../nine-turn/model/nineTurnAdapter";
import type { NineTurnLayerPhase, NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import { buildIndexDetailViewModel } from "../api/indexDetailViewModelAdapter";
import { INDEX_TECHNICAL_NINE_TURN_PERIODS, type IndexTechnicalNineTurnSummary } from "../model/indexTechnicalNineTurnSummary";
import { makeKline, makePageInit } from "../testing/indexDetailTestFixtures";
import { IndexTechnicalTab } from "./IndexTechnicalTab";

describe("IndexTechnicalTab nine-turn summary", () => {
  it("reads latestMarker only and keeps retry local to the failed period", () => {
    const onRetry = vi.fn();
    renderTab(summaryLayers({
      day: layer("day", "PARTIAL", { direction: "DOWN", sequenceNumber: 9 }),
      "30": layer("30", "ERROR", null, true),
      "60": layer("60", "SOURCE_EMPTY"),
    }), onRetry);

    const summary = screen.getByLabelText("九转序列摘要");
    const rows = Array.from(summary.querySelectorAll(".index-nine-turn-summary-row"));
    expect(rows).toHaveLength(6);
    expect(rows.map((row) => row.firstElementChild?.textContent)).toEqual(["日线", "15分钟", "30分钟", "60分钟", "90分钟", "120分钟"]);
    expect(summary).toHaveTextContent("下序 9");
    expect(summary).toHaveTextContent("部分缺失");
    expect(summary).toHaveTextContent("数据源未覆盖");
    expect(summary).toHaveTextContent("加载失败");
    expect(rows[1]).toHaveTextContent("--");
    expect(rows[4]).toHaveTextContent("--");
    expect(rows[5]).toHaveTextContent("--");
    fireEvent.click(screen.getByRole("button", { name: "重试30分钟九转" }));
    expect(onRetry).toHaveBeenCalledWith("30");
  });

  it("shows unsupported, loading, forbidden, and empty without a trading action", () => {
    renderTab(summaryLayers({
      day: layer("day", "LOADING"),
      "30": layer("30", "EMPTY"),
      "60": { ...unsupportedNineTurnLayer("60"), phase: "FORBIDDEN", message: "权限不足" },
    }));

    const summary = screen.getByLabelText("九转序列摘要");
    expect(summary).toHaveTextContent("加载中");
    expect(summary).toHaveTextContent("权限不足");
    expect(summary).toHaveTextContent("暂时空缺");
    expect(summary).toHaveTextContent("非交易信号");
    expect(summary.querySelectorAll("b.secondary")).toHaveLength(6);
    expect(screen.queryByRole("button", { name: /交易/ })).not.toBeInTheDocument();
  });
});

function renderTab(
  nineTurnSummary: IndexTechnicalNineTurnSummary,
  onNineTurnRetry = vi.fn(),
) {
  render(
    <IndexTechnicalTab
      nineTurnSummary={nineTurnSummary}
      onNineTurnRetry={onNineTurnRetry}
      onTrendRetry={vi.fn()}
      trend={null}
      trendPhase="unavailable"
      viewModel={buildIndexDetailViewModel(makePageInit(), makeKline())}
    />,
  );
}

function summaryLayers(overrides: Partial<IndexTechnicalNineTurnSummary>): IndexTechnicalNineTurnSummary {
  return {
    ...Object.fromEntries(
      INDEX_TECHNICAL_NINE_TURN_PERIODS.map(({ period }) => [period, idleNineTurnLayer(period)]),
    ) as IndexTechnicalNineTurnSummary,
    ...overrides,
  };
}

function layer(
  period: NineTurnPeriod,
  phase: NineTurnLayerPhase,
  marker: { direction: "UP" | "DOWN"; sequenceNumber: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 } | null = null,
  canRetry = false,
): NineTurnLayerViewModel {
  const base = idleNineTurnLayer(period);
  const latestMarker = marker ? {
    completed: marker.sequenceNumber === 9,
    direction: marker.direction,
    sequenceNumber: marker.sequenceNumber,
    tradeDate: "2026-07-31",
    tradeTime: period === "day" ? null : "2026-07-31T10:00:00+08:00",
  } : null;
  return {
    ...base,
    canRetry,
    data: latestMarker ? { latestMarker } as NineTurnSeriesDto : null,
    phase,
  };
}
