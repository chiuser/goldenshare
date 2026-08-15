import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { NineTurnPeriod, NineTurnSeriesDto } from "../../nine-turn/api/nineTurnApiTypes";
import { idleNineTurnLayer, unsupportedNineTurnLayer } from "../../nine-turn/model/nineTurnAdapter";
import type { NineTurnLayerPhase, NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import { buildIndexDetailViewModel } from "../api/indexDetailViewModelAdapter";
import { makeKline, makePageInit } from "../testing/indexDetailTestFixtures";
import { IndexTechnicalTab } from "./IndexTechnicalTab";

describe("IndexTechnicalTab nine-turn summary", () => {
  it("reads latestMarker only and keeps retry local to the failed period", () => {
    const onRetry = vi.fn();
    renderTab({
      day: layer("day", "PARTIAL", { direction: "DOWN", sequenceNumber: 9 }),
      "30": layer("30", "ERROR", null, true),
      "60": layer("60", "SOURCE_EMPTY"),
    }, onRetry);

    expect(screen.getByLabelText("九转序列摘要")).toHaveTextContent("下序 9");
    expect(screen.getByLabelText("九转序列摘要")).toHaveTextContent("部分缺失");
    expect(screen.getByLabelText("九转序列摘要")).toHaveTextContent("数据源未覆盖");
    expect(screen.getByLabelText("九转序列摘要")).toHaveTextContent("加载失败");
    fireEvent.click(screen.getByRole("button", { name: "重试30分钟九转" }));
    expect(onRetry).toHaveBeenCalledWith("30");
  });

  it("shows unsupported, loading, forbidden, and empty without a trading action", () => {
    renderTab({
      day: layer("day", "LOADING"),
      "30": layer("30", "EMPTY"),
      "60": { ...unsupportedNineTurnLayer("60"), phase: "FORBIDDEN", message: "权限不足" },
    });

    const summary = screen.getByLabelText("九转序列摘要");
    expect(summary).toHaveTextContent("加载中");
    expect(summary).toHaveTextContent("权限不足");
    expect(summary).toHaveTextContent("当前窗口无标记");
    expect(summary).toHaveTextContent("非交易信号");
    expect(summary.querySelectorAll("b.secondary")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /交易/ })).not.toBeInTheDocument();
  });
});

function renderTab(
  nineTurnSummary: Record<"day" | "30" | "60", NineTurnLayerViewModel>,
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
