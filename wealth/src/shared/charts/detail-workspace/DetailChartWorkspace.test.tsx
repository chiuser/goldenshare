import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DetailChartWorkspace } from "./DetailChartWorkspace";
import { buildCandlestickData, buildHistogramData, buildLineData } from "./detailChartSeries";
import type { DetailChartLineDefinition, DetailChartPoint } from "./detailChartTypes";

const chartMock = vi.hoisted(() => {
  const charts: Array<Record<string, any>> = [];
  const createChart = vi.fn((_container?: unknown, _options?: unknown) => {
    let visibleRange: { from: number; to: number } | null = null;
    const visibleRangeHandlers: Array<() => void> = [];
    const crosshairHandlers: Array<(param: { point?: { x: number; y: number }; time?: string | number }) => void> = [];
    const series: Array<Record<string, any>> = [];
    const timeScale = {
      fitContent: vi.fn(),
      getVisibleLogicalRange: vi.fn(() => visibleRange),
      setVisibleLogicalRange: vi.fn((range: { from: number; to: number }) => {
        visibleRange = range;
        visibleRangeHandlers.forEach((handler) => handler());
      }),
      subscribeVisibleLogicalRangeChange: vi.fn((handler: () => void) => visibleRangeHandlers.push(handler)),
      timeToCoordinate: vi.fn(() => 24),
      unsubscribeVisibleLogicalRangeChange: vi.fn((handler: () => void) => {
        const index = visibleRangeHandlers.indexOf(handler);
        if (index >= 0) visibleRangeHandlers.splice(index, 1);
      }),
    };
    const chart = {
      addSeries: vi.fn(() => {
        const item = {
          attachPrimitive: vi.fn(),
          coordinateToPrice: vi.fn(() => 12.34),
          detachPrimitive: vi.fn(),
          setData: vi.fn(),
        };
        series.push(item);
        return item;
      }),
      clearCrosshairPosition: vi.fn(),
      crosshairHandlers,
      remove: vi.fn(),
      series,
      setCrosshairPosition: vi.fn(),
      subscribeCrosshairMove: vi.fn((handler: (param: { point?: { x: number; y: number }; time?: string | number }) => void) => {
        crosshairHandlers.push(handler);
      }),
      timeScale: () => timeScale,
      unsubscribeCrosshairMove: vi.fn((handler: (param: { point?: { x: number; y: number }; time?: string | number }) => void) => {
        const index = crosshairHandlers.indexOf(handler);
        if (index >= 0) crosshairHandlers.splice(index, 1);
      }),
    };
    charts.push(chart);
    return chart;
  });
  return {
    charts,
    createChart,
    reset() {
      charts.splice(0, charts.length);
      createChart.mockClear();
    },
  };
});

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "CandlestickSeries",
  ColorType: { Solid: "Solid" },
  CrosshairMode: { Normal: 0 },
  HistogramSeries: "HistogramSeries",
  LineSeries: "LineSeries",
  LineStyle: { Dotted: 1 },
  createChart: chartMock.createChart,
}));

const mainLines: DetailChartLineDefinition[] = [
  { color: "#fff", id: "nullable-line", valueOf: (point) => point.changePct },
];

describe("DetailChartWorkspace", () => {
  beforeEach(() => chartMock.reset());

  it("keeps four panes synchronized on the latest 90 observations", () => {
    renderWorkspace(makePoints(100));

    expect(chartMock.charts).toHaveLength(4);
    chartMock.charts.forEach((chart) => {
      expect(chart.timeScale().getVisibleLogicalRange()).toEqual({ from: 10, to: 99 });
    });
    expect(screen.getByLabelText("共享K线主图")).toBeInTheDocument();
    expect(screen.getByLabelText("共享MACD")).toBeInTheDocument();
    expect(screen.getByLabelText("共享成交量")).toBeInTheDocument();
    expect(screen.getByLabelText("共享KDJ")).toBeInTheDocument();
  });

  it("uses whitespace or omission for null values and never converts them to zero", () => {
    const points = makePoints(3);
    points[1]!.open = null;
    points[1]!.changePct = null;
    points[1]!.volume = null;

    expect(buildCandlestickData(points)).toHaveLength(2);
    expect(buildLineData(points, (point) => point.changePct)).toEqual([
      { time: points[0]!.time, value: points[0]!.changePct },
      { time: points[1]!.time },
      { time: points[2]!.time, value: points[2]!.changePct },
    ]);
    expect(buildHistogramData(points, (point) => point.volume, () => "#fff")).toHaveLength(2);
    expect(buildLineData(points, (point) => point.changePct).some((item) => "value" in item && item.value === 0)).toBe(false);
  });

  it("synchronizes crosshair and delegates tooltip content without fallback to the last point", () => {
    const points = makePoints(100);
    points[98]!.macd = null;
    renderWorkspace(points);

    const klineHost = screen.getByLabelText("共享K线主图").querySelector(".detail-chart-host");
    Object.defineProperty(klineHost!, "clientWidth", { configurable: true, value: 400 });
    act(() => {
      chartMock.charts[0].crosshairHandlers[0]({ point: { x: 300, y: 40 }, time: points[98]!.time });
    });

    expect(screen.getByTestId("shared-tooltip")).toHaveTextContent(points[98]!.fullDate);
    expect(screen.getByTestId("shared-tooltip")).toHaveAttribute("data-side", "left");
    expect(chartMock.charts[0].setCrosshairPosition).toHaveBeenCalled();
    expect(chartMock.charts[1].clearCrosshairPosition).toHaveBeenCalled();

    act(() => {
      chartMock.charts[0].crosshairHandlers[0]({ point: { x: 100, y: 40 }, time: "2099-01-01" });
    });
    expect(screen.queryByTestId("shared-tooltip")).not.toBeInTheDocument();
  });

  it("uses minute time scale semantics without changing the four-pane skeleton", () => {
    const points = makePoints(100);
    points[98]!.time = 1_775_010_480 as DetailChartPoint["time"];
    points[98]!.fullDate = "2026-04-01T11:08:00+08:00";
    renderWorkspace(points, "minute");

    act(() => {
      chartMock.charts[0].crosshairHandlers[0]({ point: { x: 100, y: 40 }, time: points[98]!.time });
    });
    expect(document.querySelector(".detail-chart-crosshair-date-label")).toHaveTextContent("20260401 11:08");
    expect(chartMock.createChart).toHaveBeenCalledTimes(4);
    expect(chartMock.createChart.mock.calls[3]?.[1]).toMatchObject({
      timeScale: { secondsVisible: false, timeVisible: true, visible: true },
    });
  });
});

function renderWorkspace(points: DetailChartPoint[], timeMode: "daily" | "minute" = "daily") {
  return render(
    <DetailChartWorkspace
      ariaLabel="共享图表区"
      bottomBar={<span>bottom</span>}
      bottomBarAriaLabel="共享指标栏"
      mainLines={mainLines}
      panelAriaLabels={{
        kline: "共享K线主图",
        macd: "共享MACD",
        volume: "共享成交量",
        kdj: "共享KDJ",
      }}
      points={points}
      renderMainHeader={(point) => <span>{point?.fullDate}</span>}
      renderPanelHeader={(panel) => <span>{panel}</span>}
      renderTooltip={(point, side) => <span data-side={side} data-testid="shared-tooltip">{point.fullDate}</span>}
      timeAxisAriaLabel="共享日线时间轴"
      timeMode={timeMode}
    />,
  );
}

function makePoints(count: number): DetailChartPoint[] {
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10);
    return {
      time: date,
      fullDate: date,
      open: 10 + index,
      high: 11 + index,
      low: 9 + index,
      close: 10.5 + index,
      preClose: 10 + index,
      changePct: 1 + index,
      amplitude: 2 + index,
      volume: 100 + index,
      amount: 1000 + index,
      turnoverRate: 1.2,
      macd: 0.3,
      dif: 0.1,
      dea: 0.2,
      k: 44,
      d: 55,
      j: 66,
      overlays: {},
    };
  });
}
