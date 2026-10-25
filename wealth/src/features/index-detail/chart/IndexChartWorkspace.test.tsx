import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DetailChartWorkspaceProps } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { idleNineTurnLayer } from "../../nine-turn/model/nineTurnAdapter";
import { NineTurnMarkerPrimitive } from "../../../shared/charts/detail-workspace/NineTurnMarkerPrimitive";
import { buildIndexDetailViewModel } from "../api/indexDetailViewModelAdapter";
import { makeKline, makePageInit } from "../testing/indexDetailTestFixtures";
import { IndexChartWorkspace } from "./IndexChartWorkspace";
import { TrendChannelPanePrimitive } from "../../../shared/charts/trend-channel/TrendChannelPanePrimitive";
import { dailyWaveKlineFixture, dailyWaveReadyFixture } from "../daily-wave/dailyWaveFixtures.test-support";
import { toCandlePoint } from "../api/indexDetailViewModelAdapter";
import type { DailyWaveReviewState } from "../daily-wave/types";

const workspaceMock = vi.hoisted(() => ({
  props: [] as DetailChartWorkspaceProps[],
  reset() { this.props.splice(0, this.props.length); },
}));

vi.mock("../xxm/useIndexXxmLayer", () => ({ useIndexXxmLayer: () => ({ phase: "unsupported", data: null, errorMessage: "", requestKey: "", retry: () => {}, macdPrimitives: [] }) }));

vi.mock("../../../shared/charts/detail-workspace/DetailChartWorkspace", () => ({
  DetailChartWorkspace: (props: DetailChartWorkspaceProps) => {
    workspaceMock.props.push(props);
    return <div>{props.renderMainHeader(props.points.at(-1) ?? null)}{props.bottomBar}</div>;
  },
}));

describe("IndexChartWorkspace adapter", () => {
  beforeEach(() => workspaceMock.reset());

  it("updates asynchronous research trend content without replacing chart primitives or changing the selected overlay", () => {
    const viewModel = buildIndexDetailViewModel(makePageInit(), makeKline());
    const review: DailyWaveReviewState = { supported: true, enabled: true, phase: "ready", response: dailyWaveReadyFixture(),
      candles: dailyWaveKlineFixture().bars.map(toCandlePoint), dataKey: "index:000001.SH:day:wave-review:literal-review",
      errorMessage: "", toggle: vi.fn(), retry: vi.fn(), close: vi.fn() };
    const props = { nineTurnLayer: idleNineTurnLayer("day"), onNineTurnRetry: vi.fn(), viewModel, review };
    const { rerender } = render(<IndexChartWorkspace {...props} trend={null} trendPhase="loading" />);
    const first = latestProps();
    const trend = { droppedCount: 0, status: "READY" as const, points: [{ time: "2023-10-26", close: 120,
      shortUpper: 122, shortLower: 115, longUpper: 125, longLower: 112 }] };
    rerender(<IndexChartWorkspace {...props} trend={trend} trendPhase="ready" />);
    expect(latestProps().mainPrimitives).toBe(first.mainPrimitives);
    expect(latestProps().mainLines).toBe(first.mainLines);
    expect(latestProps().dataKey).toBe(first.dataKey);
    fireEvent.change(screen.getByLabelText("指数主图指标切换"), { target: { value: "TREND_CHANNEL" } });
    const selected = latestProps();
    rerender(<IndexChartWorkspace {...props} trend={{ ...trend, points: [{ ...trend.points[0]!, shortUpper: 123 }] }} trendPhase="ready" />);
    expect(latestProps().mainPrimitives).toBe(selected.mainPrimitives);
    expect(latestProps().mainLines).toBe(selected.mainLines);
  });

  it("uses the index daily dataKey and keeps it stable across MA/BOLL switches", () => {
    const viewModel = buildIndexDetailViewModel(makePageInit("399001.SZ"), makeKline("399001.SZ"));
    render(<IndexChartWorkspace nineTurnLayer={idleNineTurnLayer("day")} onNineTurnRetry={vi.fn()} trend={null} trendPhase="unavailable" viewModel={viewModel} />);

    expect(latestProps().dataKey).toBe("index:399001.SZ:day");
    fireEvent.change(screen.getByLabelText("指数主图指标切换"), { target: { value: "BOLL" } });
    expect(latestProps().dataKey).toBe("index:399001.SZ:day");
    expect(latestProps().mainLines).toHaveLength(3);
  });

  it("keeps the same dataKey when the SSE trend primitive is active", () => {
    const viewModel = buildIndexDetailViewModel(makePageInit(), makeKline());
    render(
      <IndexChartWorkspace
        nineTurnLayer={idleNineTurnLayer("day")}
        onNineTurnRetry={vi.fn()}
        trend={{
          droppedCount: 0,
          status: "READY",
          points: viewModel.chart.candles.map((point) => ({
            time: point.time,
            close: point.close ?? 0,
            shortUpper: 4_000,
            shortLower: 3_900,
            longUpper: 4_050,
            longLower: 3_850,
          })),
        }}
        trendPhase="ready"
        viewModel={viewModel}
      />,
    );

    expect(latestProps().dataKey).toBe("index:000001.SH:day");
    expect(latestProps().mainPrimitives).toHaveLength(2);
    expect(latestProps().mainPrimitives?.[0]).toBeInstanceOf(TrendChannelPanePrimitive);
    expect(latestProps().mainPrimitives?.[1]).toBeInstanceOf(NineTurnMarkerPrimitive);
    expect(latestProps().mainLines).toHaveLength(0);
  });
});

function latestProps() {
  const props = workspaceMock.props.at(-1);
  if (!props) throw new Error("DetailChartWorkspace was not rendered");
  return props;
}
