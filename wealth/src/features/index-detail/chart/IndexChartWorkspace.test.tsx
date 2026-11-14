import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { DetailChartIndicatorPanelKey, DetailChartWorkspaceProps } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { idleNineTurnLayer } from "../../nine-turn/model/nineTurnAdapter";
import { NineTurnMarkerPrimitive } from "../../../shared/charts/detail-workspace/NineTurnMarkerPrimitive";
import { buildIndexDetailViewModel } from "../api/indexDetailViewModelAdapter";
import { makeKline, makePageInit } from "../testing/indexDetailTestFixtures";
import { IndexChartWorkspace } from "./IndexChartWorkspace";
import { TrendChannelPanePrimitive } from "../../../shared/charts/trend-channel/TrendChannelPanePrimitive";
import { fetchXxm } from "../xxm/apiClient";
import { decodeXxmDebug } from "../debug/xxmDebugContract";
import { xxmDebugFixture } from "../xxm/xxmFixtures.test-support";

const workspaceMock = vi.hoisted(() => ({
  props: [] as DetailChartWorkspaceProps[],
  reset() { this.props.splice(0, this.props.length); },
}));
const nineTurnControl = { available: true, visible: true, onToggle: vi.fn() };
const defaultIndicatorControls = { hiddenIndicatorPanels: new Set<never>(), onToggleIndicatorPanel: vi.fn(), quantitativeStructureAvailable: false };

vi.mock("../xxm/apiClient", async (importOriginal) => ({
  ...await importOriginal<typeof import("../xxm/apiClient")>(),
  fetchXxm: vi.fn(),
}));

vi.mock("../../../shared/charts/detail-workspace/DetailChartWorkspace", () => ({
  DetailChartWorkspace: (props: DetailChartWorkspaceProps) => {
    workspaceMock.props.push(props);
    return <div>{props.renderMainHeader(props.points.at(-1) ?? null)}{props.bottomBar}</div>;
  },
}));

describe("IndexChartWorkspace adapter", () => {
  beforeEach(() => {
    workspaceMock.reset();
    vi.mocked(fetchXxm).mockReset().mockReturnValue(new Promise(() => {}));
  });

  it("toggles MA lines and header values together without a selector", () => {
    const viewModel = buildIndexDetailViewModel(makePageInit(), makeKline());
    const history = { active: true, visible: null, phase: "idle" as const, error: undefined, onViewport: vi.fn(), retryLayer: vi.fn() };
    const props = {
      indicatorControls: defaultIndicatorControls, nineTurnControl, nineTurnLayer: idleNineTurnLayer("day"),
      onNineTurnRetry: vi.fn(), recognitionEnabled: false, viewModel, history,
    };
    const view = render(<IndexChartWorkspace {...props} trend={null} trendPhase="loading" />);
    const first = latestProps();
    expect(first.mainLines.map(line => line.id)).toEqual(["ma5", "ma10", "ma20", "ma30", "ma60", "ma90", "ma250"]);
    for (const text of ["MA5:3900.00", "MA10:3890.00", "MA20:3880.00", "MA30:3870.00", "MA60:3860.00", "MA90:3850.00", "MA250:3800.00"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    const ma = screen.getByRole("button", { name: "均线" });
    fireEvent.click(ma);
    expect(ma).toHaveAttribute("aria-pressed", "false");
    expect(ma).not.toHaveClass("active");
    expect(latestProps().mainLines).toEqual([]);
    expect(screen.queryAllByText(/^MA\d+:/)).toHaveLength(0);
    const closed = latestProps();
    const trend = { droppedCount: 0, status: "READY" as const, points: viewModel.chart.candles.map(point => ({
      time: point.time, close: point.close ?? 0, shortUpper: 4000, shortLower: 3900, longUpper: 4050, longLower: 3850,
    })) };
    const olderCandle = { ...viewModel.chart.candles[0]!, time: "2026-07-29", fullDate: "2026-07-29" };
    view.rerender(<IndexChartWorkspace {...props} trend={trend} trendPhase="ready" history={{ ...history,
      visible: { candles: [olderCandle, ...viewModel.chart.candles], failedLayers: [], nineTurnMarkers: [], trendPoints: [] },
    }} />);
    expect(latestProps().points).toHaveLength(3);
    expect(latestProps().mainLines).toEqual([]);
    expect(latestProps().mainPrimitives).toBe(closed.mainPrimitives);
    expect(latestProps().dataKey).toBe(first.dataKey);
    expect(screen.queryAllByText(/^MA\d+:/)).toHaveLength(0);
    fireEvent.click(ma);
    expect(ma).toHaveAttribute("aria-pressed", "true");
    expect(latestProps().mainLines).toHaveLength(7);
    // The public kline fixture's nullable fields are mapped by the real adapter.
    const currentPoint = { ...latestProps().points[0]!, overlays: { ma5: 0, ma10: null, ma20: 12, ma30: 13, ma60: 14, ma90: 15, ma250: 16 } };
    const header = render(latestProps().renderMainHeader(currentPoint));
    expect(within(header.container).getByText("MA5:0.00")).toBeInTheDocument();
    expect(within(header.container).getByText("MA10:--")).toBeInTheDocument();
    header.unmount();
    fireEvent.click(screen.getByRole("button", { name: "BOLL" }));
    expect(ma).toHaveAttribute("aria-pressed", "false");
    expect(latestProps().mainLines).toHaveLength(3);
    expect(screen.getByText("BOLLUPPER:4000.00")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "指数主图指标切换" })).not.toBeInTheDocument();
    expect(fetchXxm).not.toHaveBeenCalled();
    expect(history.onViewport).not.toHaveBeenCalled();
  });

  it("updates asynchronous ordinary trend content without replacing chart primitives or changing the selected overlay", () => {
    const viewModel = buildIndexDetailViewModel(makePageInit(), makeKline());
    const props = { indicatorControls: defaultIndicatorControls, nineTurnControl, nineTurnLayer: idleNineTurnLayer("day"), onNineTurnRetry: vi.fn(), viewModel };
    const { rerender } = render(<IndexChartWorkspace recognitionEnabled {...props} trend={null} trendPhase="loading" />);
    const first = latestProps();
    fireEvent.click(screen.getByRole("button", { name: "BOLL" }));
    const trend = { droppedCount: 0, status: "READY" as const, points: [{ time: "2023-10-26", close: 120,
      shortUpper: 122, shortLower: 115, longUpper: 125, longLower: 112 }] };
    rerender(<IndexChartWorkspace recognitionEnabled {...props} trend={trend} trendPhase="ready" />);
    expect(screen.getByRole("button", { name: "BOLL" })).toHaveClass("active");
    expect(latestProps().mainLines).toHaveLength(3);
    expect(latestProps().dataKey).toBe(first.dataKey);
    fireEvent.click(screen.getByRole("button", { name: "趋势通道" }));
    const selected = latestProps();
    rerender(<IndexChartWorkspace recognitionEnabled {...props} trend={{ ...trend, points: [{ ...trend.points[0]!, shortUpper: 123 }] }} trendPhase="ready" />);
    expect(latestProps().mainPrimitives).toBe(selected.mainPrimitives);
    expect(latestProps().mainLines).toBe(selected.mainLines);
  });

  it("uses the index daily dataKey and keeps it stable across MA/BOLL switches", () => {
    const viewModel = buildIndexDetailViewModel(makePageInit("399001.SZ"), makeKline("399001.SZ"));
    const onToggleIndicatorPanel = vi.fn();
    render(<IndexChartWorkspace recognitionEnabled indicatorControls={{ ...defaultIndicatorControls, hiddenIndicatorPanels: new Set(["volume"]), onToggleIndicatorPanel }} nineTurnControl={nineTurnControl} nineTurnLayer={idleNineTurnLayer("day")} onNineTurnRetry={vi.fn()} trend={null} trendPhase="unavailable" viewModel={viewModel} />);

    expect(latestProps().dataKey).toBe("index:399001.SZ:day");
    expect(latestProps().hiddenIndicatorPanels).toEqual(new Set(["volume"]));
    expect(screen.getByRole("button", { name: "成交额" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "MACD", pressed: true })).toHaveClass("active");
    expect(screen.getByRole("button", { name: "KDJ", pressed: true })).toHaveClass("active");
    const structure = screen.getByRole("button", { name: "量化结构", pressed: false });
    expect(structure).toBeDisabled();
    expect(screen.getByRole("button", { name: "KDJ" }).nextElementSibling).toBe(structure);
    expect(structure.nextElementSibling).toBe(screen.getByRole("button", { name: "九转序列", pressed: true }));
    fireEvent.click(screen.getByRole("button", { name: "VOL", pressed: false }));
    expect(onToggleIndicatorPanel).toHaveBeenCalledWith("volume");
    fireEvent.click(screen.getByRole("button", { name: "BOLL" }));
    expect(latestProps().dataKey).toBe("index:399001.SZ:day");
    expect(latestProps().mainLines).toHaveLength(3);
    expect(onToggleIndicatorPanel).toHaveBeenCalledTimes(1);
  });

  it("keeps the same dataKey when the SSE trend primitive is active", () => {
    const viewModel = buildIndexDetailViewModel(makePageInit(), makeKline());
    render(
      <IndexChartWorkspace recognitionEnabled
        indicatorControls={defaultIndicatorControls}
        nineTurnControl={nineTurnControl}
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

  it("shows only the first recognition window and gates its hover details without refetching", async () => {
    const { response } = xxmDebugFixture("000001.SH");
    const kline = makeKline();
    const tradeDate = "2023-01-12";
    const previousDate = "2023-01-11";
    const seed = { ...kline.bars[1]!, tradeDate, open: 105, high: 106, low: 102, close: 104, preClose: 105 };
    const previous = { ...kline.bars[0]!, tradeDate: previousDate, open: 103, high: 106, low: 102, close: 105, preClose: 103 };
    vi.mocked(fetchXxm).mockResolvedValueOnce({ response, deadline: performance.now() + 5000 });
    const viewModel = buildIndexDetailViewModel(makePageInit(), { ...kline, bars: [seed] });
    const allCandles = buildIndexDetailViewModel(makePageInit(), { ...kline, bars: [previous, seed] }).chart.candles;
    const controls = { ...defaultIndicatorControls, quantitativeStructureAvailable: true };
    const base = {
      nineTurnControl, nineTurnLayer: idleNineTurnLayer("day"), onNineTurnRetry: vi.fn(), viewModel,
      trend: null, trendPhase: "unavailable" as const,
      recognitionEnabled: true,
    };
    const history = {
      active: true, visible: null, phase: "idle" as const, error: undefined,
      onViewport: vi.fn(), retryLayer: vi.fn(),
    };
    const hidden = new Set<DetailChartIndicatorPanelKey>(["quantitativeStructure", "kdj"]);
    const rendered = render(<IndexChartWorkspace {...base} history={history} indicatorControls={{ ...controls, hiddenIndicatorPanels: hidden }} />);
    await waitFor(() => expect(latestProps().quantitativeStructure?.valuesAt(tradeDate)).toEqual({ dif: 96, dea: 95, macd: 2 }));
    const first = latestProps();
    const valuesAt = first.quantitativeStructure?.valuesAt;
    const latest = first.points[0]!;
    expect(latest.macd).toBe(1);
    const tooltip = render(first.renderTooltip(latest, "right"));
    expect(screen.queryByLabelText("顶底识别详情")).not.toBeInTheDocument();

    rendered.rerender(<IndexChartWorkspace {...base} history={history} indicatorControls={{ ...controls, hiddenIndicatorPanels: new Set(["kdj"]) }} />);
    tooltip.rerender(latestProps().renderTooltip(latest, "right"));
    expect(screen.getByLabelText("顶底识别详情")).toBeInTheDocument();
    expect(screen.getByLabelText("顶底识别详情")).toHaveTextContent("顶消失 / 顶钝化");
    const header = render(latestProps().quantitativeStructure?.renderHeader(valuesAt!(tradeDate)));
    expect(header.getByText("DIF:96.00")).toBeInTheDocument();
    expect(header.getByText("MACD:2.00")).toBeInTheDocument();

    rendered.rerender(<IndexChartWorkspace {...base} indicatorControls={{ ...controls, hiddenIndicatorPanels: new Set(["kdj"]) }}
      history={{ ...history, visible: { candles: allCandles, failedLayers: [], nineTurnMarkers: [], trendPoints: [] } }} />);
    expect(latestProps().points).toHaveLength(2);
    expect(latestProps().quantitativeStructure?.valuesAt).toBe(valuesAt);
    expect(valuesAt?.(previousDate)).toBeNull();
    tooltip.rerender(latestProps().renderTooltip(latestProps().points[0]!, "right"));
    expect(screen.queryByLabelText("顶底识别详情")).not.toBeInTheDocument();
    expect(screen.queryByText("识别调试内容")).not.toBeInTheDocument();
    expect(fetchXxm).toHaveBeenCalledTimes(1);
    expect(fetchXxm).toHaveBeenCalledWith(expect.objectContaining({ startDate: tradeDate, endDate: tradeDate, limit: 1 }), expect.any(AbortSignal));
  });

  it("merges the first and historical nine-turn markers before changing their drawing visibility", () => {
    const kline = makeKline();
    const olderBar = { ...kline.bars[0]!, tradeDate: "2023-01-11" };
    const firstBar = { ...kline.bars[1]!, tradeDate: "2023-01-12" };
    const marker = (tradeDate: string, sequenceNumber: 2 | 3) =>
      ({ tradeDate, tradeTime: null, sequenceNumber, direction: "UP" as const, completed: false });
    const viewModel = buildIndexDetailViewModel(makePageInit(), { ...kline, bars: [firstBar] });
    const candles = buildIndexDetailViewModel(makePageInit(), { ...kline, bars: [olderBar, firstBar] }).chart.candles;
    const history = {
      active: true, phase: "idle" as const, error: undefined, onViewport: vi.fn(), retryLayer: vi.fn(),
      visible: { candles, failedLayers: [], trendPoints: [], nineTurnMarkers: [marker("2023-01-11", 2)] },
    };
    const props = {
      viewModel, history, indicatorControls: defaultIndicatorControls, recognitionEnabled: false,
      trend: null, trendPhase: "unavailable" as const, onNineTurnRetry: vi.fn(),
      nineTurnLayer: { ...idleNineTurnLayer("day"), phase: "READY" as const, markers: [marker("2023-01-12", 3)] },
    };
    const setMarkers = vi.spyOn(NineTurnMarkerPrimitive.prototype, "setMarkers");
    const setVisible = vi.spyOn(NineTurnMarkerPrimitive.prototype, "setVisible");
    try {
      const rendered = render(<IndexChartWorkspace {...props} nineTurnControl={nineTurnControl} />);
      const original = latestProps();
      expect(setMarkers.mock.lastCall?.[0].map(item => [item.time, item.sequenceNumber]))
        .toEqual([["2023-01-11", 2], ["2023-01-12", 3]]);
      setMarkers.mockClear();
      setVisible.mockClear();
      rendered.rerender(<IndexChartWorkspace {...props} nineTurnControl={{ ...nineTurnControl, visible: false }} />);
      rendered.rerender(<IndexChartWorkspace {...props} nineTurnControl={nineTurnControl} />);
      expect(setVisible.mock.calls).toEqual([[false], [true]]);
      expect(setVisible.mock.contexts).toEqual([original.mainPrimitives?.[0], original.mainPrimitives?.[0]]);
      expect(latestProps().mainPrimitives).toBe(original.mainPrimitives);
      expect(setMarkers).not.toHaveBeenCalled();
      expect(history.onViewport).not.toHaveBeenCalled();
    } finally {
      setVisible.mockRestore();
      setMarkers.mockRestore();
    }
  });
});

function latestProps() {
  const props = workspaceMock.props.at(-1);
  if (!props) throw new Error("DetailChartWorkspace was not rendered");
  return props;
}
