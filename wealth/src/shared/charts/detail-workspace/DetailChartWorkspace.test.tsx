import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

import { DetailChartWorkspace } from "./DetailChartWorkspace";
import { VisibleExtremaPrimitive } from "./VisibleExtremaPrimitive";
import { buildCandlestickData, buildHistogramData, buildLineData } from "./detailChartSeries";
import type {
  DetailChartLineDefinition,
  DetailChartPoint,
  DetailChartWorkspaceProps,
} from "./detailChartTypes";

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
    const chart: Record<string, any> = {
      addSeries: vi.fn(() => {
        const item: Record<string, any> = {
          attachedPrimitives: [] as any[],
          attachPrimitive: vi.fn((primitive: any) => {
            item.attachedPrimitives.push(primitive);
            primitive.attached?.({
              chart,
              requestUpdate: vi.fn(),
              series: item,
            });
          }),
          coordinateToPrice: vi.fn(() => 12.34),
          detachPrimitive: vi.fn((primitive: any) => {
            const index = item.attachedPrimitives.indexOf(primitive);
            if (index >= 0) item.attachedPrimitives.splice(index, 1);
            primitive.detached?.();
          }),
          priceToCoordinate: vi.fn((price: number) => price),
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

const defaultResizeObserver = globalThis.ResizeObserver;
const resizeObserverMock = {
  instances: [] as ControlledResizeObserver[],
  reset() {
    this.instances.splice(0, this.instances.length);
  },
};

class ControlledResizeObserver implements ResizeObserver {
  readonly observed = new Set<Element>();
  disconnected = false;

  constructor(private readonly callback: ResizeObserverCallback) {
    resizeObserverMock.instances.push(this);
  }

  disconnect() {
    this.disconnected = true;
    this.observed.clear();
  }

  observe(target: Element) {
    this.observed.add(target);
  }

  unobserve(target: Element) {
    this.observed.delete(target);
  }

  trigger(target: Element, width: number) {
    this.callback([
      {
        borderBoxSize: [] as unknown as ResizeObserverSize[],
        contentBoxSize: [] as unknown as ResizeObserverSize[],
        contentRect: { bottom: 0, height: 0, left: 0, right: width, top: 0, width, x: 0, y: 0, toJSON: () => ({}) },
        devicePixelContentBoxSize: [] as unknown as ResizeObserverSize[],
        target,
      },
    ], this);
  }
}

const mainLines: DetailChartLineDefinition[] = [
  { color: "#fff", id: "nullable-line", valueOf: (point) => point.changePct },
];

describe("DetailChartWorkspace", () => {
  beforeEach(() => {
    chartMock.reset();
    resizeObserverMock.reset();
    globalThis.ResizeObserver = ControlledResizeObserver;
  });

  afterAll(() => {
    globalThis.ResizeObserver = defaultResizeObserver;
  });

  it("keeps four panes synchronized on the latest adaptive 120 observations", () => {
    renderWorkspace(makePoints(300));

    expect(chartMock.charts).toHaveLength(4);
    chartMock.charts.forEach((chart) => {
      expect(chart.timeScale().getVisibleLogicalRange()).toEqual({ from: 180, to: 299 });
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
    expect(document.querySelector(".detail-chart-crosshair-vertical")).toHaveStyle({ left: "24px" });
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

  it("formats native minute axes in Shanghai time without rendering the shared overlay twice", () => {
    const points = makePoints(300);
    points[298]!.time = 1_784_259_000 as DetailChartPoint["time"];
    points[298]!.fullDate = "2026-07-17T11:30:00+08:00";
    render(
      <DetailChartWorkspace
        ariaLabel="共享图表区"
        crosshairPresentation="native-axis-labels"
        dataKey="stock:000001.SZ:m5"
        mainLines={mainLines}
        panelAriaLabels={{
          kline: "共享K线主图",
          macd: "共享MACD",
          volume: "共享成交量",
          kdj: "共享KDJ",
        }}
        points={points}
        renderMainHeader={() => <span>main</span>}
        renderPanelHeader={(panel) => <span>{panel}</span>}
        renderTooltip={(point) => <span>{point.fullDate}</span>}
        timeAxisAriaLabel="共享分钟时间轴"
        timeAxisPlacement="each-pane"
        timeMode="minute"
        topRightAccessory={<span role="status">READY</span>}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent("READY");
    const spacer = document.querySelector(".detail-chart-indicator-spacer");
    expect(spacer).toHaveAttribute("aria-hidden", "true");
    expect(chartMock.createChart).toHaveBeenCalledTimes(4);
    chartMock.createChart.mock.calls.forEach((call) => {
      const options = call[1] as Record<string, any>;
      expect(call[1]).toMatchObject({
        crosshair: { mode: 0 },
        localization: { timeFormatter: expect.any(Function) },
        rightPriceScale: { autoScale: true },
        timeScale: { secondsVisible: false, tickMarkFormatter: expect.any(Function), timeVisible: true, visible: true },
      });
      expect(options.crosshair).not.toHaveProperty("vertLine");
      expect(options.localization.timeFormatter(1_784_259_000)).toBe("07-17 11:30");
      expect(options.timeScale.tickMarkFormatter(1_784_259_000)).toBe("07-17 11:30");
    });
    act(() => {
      chartMock.charts[0].crosshairHandlers[0]({ point: { x: 100, y: 40 }, time: points[298]!.time });
    });
    expect(document.querySelector(".detail-chart-crosshair-vertical")).not.toBeInTheDocument();
    expect(document.querySelector(".detail-chart-crosshair-date-label")).not.toBeInTheDocument();
    chartMock.charts.forEach((chart) => {
      expect(chart.timeScale().getVisibleLogicalRange()).toEqual({ from: 180, to: 299 });
    });
  });

  it("keeps the existing synchronized-overlay and bottom-pane defaults", () => {
    renderWorkspace(makePoints(100), "minute");

    expect(chartMock.createChart.mock.calls.slice(0, 3).every((call) => {
      const options = call[1] as Record<string, any>;
      return options.timeScale.visible === false;
    })).toBe(true);
    expect(chartMock.createChart.mock.calls[3]?.[1]).toMatchObject({
      crosshair: {
        horzLine: { labelVisible: false },
        vertLine: { labelVisible: false, visible: false },
      },
      rightPriceScale: { autoScale: true },
      timeScale: { visible: true },
    });
    expect(screen.getByLabelText("共享指标栏")).toHaveTextContent("bottom");
    expect(document.querySelector(".detail-chart-indicator-spacer")).not.toBeInTheDocument();
  });

  it("zooms all four panes in 15-bar steps without rebuilding charts or requesting data", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderWorkspace(makePoints(300));
    chartMock.charts.forEach((chart) => chart.timeScale().setVisibleLogicalRange.mockClear());
    const createCount = chartMock.createChart.mock.calls.length;
    const fetchCount = fetchSpy.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "放大K线，减少可见根数" }));

    expect(chartMock.createChart).toHaveBeenCalledTimes(createCount);
    expect(fetchSpy).toHaveBeenCalledTimes(fetchCount);
    chartMock.charts.forEach((chart) => {
      expect(chart.timeScale().setVisibleLogicalRange).toHaveBeenCalledTimes(1);
      expect(chart.timeScale().getVisibleLogicalRange()).toEqual({ from: 195, to: 299 });
      expect(chart.timeScale().fitContent).not.toHaveBeenCalled();
    });
    fetchSpy.mockRestore();
  });

  it("attaches the built-in extrema primitive before external business primitives", () => {
    const externalPrimitive = {
      attached: vi.fn(),
      detached: vi.fn(),
      paneViews: () => [],
    };
    const rendered = render(workspaceElement(
      makePoints(300),
      "daily",
      "shared:primitives:day",
      mainLines,
      [externalPrimitive as never],
    ));
    const candleSeries = chartMock.charts[0].series[0];

    expect(candleSeries.attachedPrimitives).toHaveLength(2);
    expect(candleSeries.attachedPrimitives[0]).toBeInstanceOf(VisibleExtremaPrimitive);
    expect(candleSeries.attachedPrimitives[1]).toBe(externalPrimitive);
    expect(externalPrimitive.attached).toHaveBeenCalledTimes(1);

    rendered.unmount();
    expect(candleSeries.attachedPrimitives).toHaveLength(0);
    expect(externalPrimitive.detached).toHaveBeenCalledTimes(1);
  });

  it("resolves extrema from the new range after zoom without rebuilding charts", () => {
    renderWorkspace(makePoints(300));
    const candleSeries = chartMock.charts[0].series[0];
    const primitive = candleSeries.attachedPrimitives[0] as VisibleExtremaPrimitive;
    const before = primitiveDrawingTarget();
    primitive.draw(before.target);
    expect(before.fillText).toHaveBeenCalledWith("310.00", expect.any(Number), 310);
    expect(before.fillText).toHaveBeenCalledWith("189.00", expect.any(Number), 189);
    const createCount = chartMock.createChart.mock.calls.length;

    fireEvent.click(screen.getByRole("button", { name: "放大K线，减少可见根数" }));
    const after = primitiveDrawingTarget();
    primitive.draw(after.target);

    expect(chartMock.createChart).toHaveBeenCalledTimes(createCount);
    expect(after.fillText).toHaveBeenCalledWith("310.00", expect.any(Number), 310);
    expect(after.fillText).toHaveBeenCalledWith("204.00", expect.any(Number), 204);
  });

  it("disables zoom-in at 45 and zoom-out at 180", () => {
    renderWorkspace(makePoints(300));
    const zoomIn = screen.getByRole("button", { name: "放大K线，减少可见根数" });
    const zoomOut = screen.getByRole("button", { name: "缩小K线，增加可见根数" });

    for (let index = 0; index < 5; index += 1) fireEvent.click(zoomIn);
    expect(zoomIn).toBeDisabled();
    expect(zoomOut).toBeEnabled();
    expect(chartMock.charts[0].timeScale().getVisibleLogicalRange()).toEqual({ from: 255, to: 299 });

    for (let index = 0; index < 9; index += 1) fireEvent.click(zoomOut);
    expect(zoomOut).toBeDisabled();
    expect(zoomIn).toBeEnabled();
    expect(chartMock.charts[0].timeScale().getVisibleLogicalRange()).toEqual({ from: 120, to: 299 });
  });

  it("shows disabled controls for short data and no controls for empty data", () => {
    const rendered = renderWorkspace(makePoints(44));
    expect(screen.getByRole("button", { name: "放大K线，减少可见根数" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "缩小K线，增加可见根数" })).toBeDisabled();

    rendered.rerender(workspaceElement([], "daily", "shared:empty:day"));
    expect(screen.queryByRole("group", { name: "K线缩放" })).not.toBeInTheDocument();
  });

  it("uses the real point count as the zoom-out ceiling below 180", () => {
    renderWorkspace(makePoints(100), "daily", "shared:100:day");
    expect(screen.getByRole("button", { name: "缩小K线，增加可见根数" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "放大K线，减少可见根数" })).toBeEnabled();
  });

  it("restores an adjusted range across overlay rebuilds and resets for a new dataKey", () => {
    const points = makePoints(300);
    const rendered = renderWorkspace(points);
    fireEvent.click(screen.getByRole("button", { name: "放大K线，减少可见根数" }));

    rendered.rerender(workspaceElement(points, "daily", "shared:test:daily", [
      { color: "#abc", id: "next-line", valueOf: (point) => point.close },
    ]));
    expect(chartMock.charts.slice(-4).every((chart) => (
      JSON.stringify(chart.timeScale().getVisibleLogicalRange()) === JSON.stringify({ from: 195, to: 299 })
    ))).toBe(true);

    rendered.rerender(workspaceElement(points, "daily", "shared:next:daily"));
    expect(chartMock.charts.slice(-4).every((chart) => (
      JSON.stringify(chart.timeScale().getVisibleLogicalRange()) === JSON.stringify({ from: 180, to: 299 })
    ))).toBe(true);
  });

  it("restores the latest adaptive range when an untouched chart callback reports a stale range", () => {
    const points = makePoints(300);
    const rendered = renderWorkspace(points, "minute", "shared:stale:m60");
    act(() => {
      chartMock.charts[0].timeScale().setVisibleLogicalRange({ from: 0, to: 119 });
    });

    rendered.rerender(workspaceElement(points, "minute", "shared:stale:m60", [
      { color: "#abc", id: "loaded-indicator", valueOf: (point) => point.close },
    ]));

    expect(chartMock.charts.slice(-4).every((chart) => (
      JSON.stringify(chart.timeScale().getVisibleLogicalRange()) === JSON.stringify({ from: 180, to: 299 })
    ))).toBe(true);
  });

  it("adapts an untouched range on resize but preserves a user-adjusted range", () => {
    vi.useFakeTimers();
    renderWorkspace(makePoints(300));
    const host = screen.getByLabelText("共享K线主图").querySelector(".detail-chart-host")!;
    const observer = resizeObserverMock.instances.at(-1)!;
    act(() => {
      observer.trigger(host, 800);
      vi.runAllTimers();
    });
    expect(chartMock.charts[0].timeScale().getVisibleLogicalRange()).toEqual({ from: 225, to: 299 });

    fireEvent.click(screen.getByRole("button", { name: "放大K线，减少可见根数" }));
    expect(chartMock.charts[0].timeScale().getVisibleLogicalRange()).toEqual({ from: 240, to: 299 });
    act(() => {
      observer.trigger(host, 1193);
      vi.runAllTimers();
    });
    expect(chartMock.charts[0].timeScale().getVisibleLogicalRange()).toEqual({ from: 240, to: 299 });
    vi.useRealTimers();
  });

  it("follows appended latest data but keeps a historical observation range", () => {
    const points = makePoints(300);
    const latestRendered = renderWorkspace(points, "daily", "shared:append:day");
    latestRendered.rerender(workspaceElement(makePoints(301), "daily", "shared:append:day"));
    expect(chartMock.charts.slice(-4).every((chart) => (
      JSON.stringify(chart.timeScale().getVisibleLogicalRange()) === JSON.stringify({ from: 181, to: 300 })
    ))).toBe(true);
    latestRendered.unmount();

    chartMock.reset();
    const historicalRendered = renderWorkspace(points, "daily", "shared:history:day");
    const historicalHost = screen.getByLabelText("共享K线主图").querySelector(".detail-chart-host")!;
    Object.defineProperty(historicalHost, "clientWidth", { configurable: true, value: 1000 });
    fireEvent.mouseDown(historicalHost, { button: 0, clientX: 500 });
    fireEvent.mouseMove(window, { clientX: 1500 });
    fireEvent.mouseUp(window);
    const historicalRange = chartMock.charts[0].timeScale().getVisibleLogicalRange();
    historicalRendered.rerender(workspaceElement(makePoints(301), "daily", "shared:history:day"));
    expect(chartMock.charts.slice(-4).every((chart) => (
      JSON.stringify(chart.timeScale().getVisibleLogicalRange()) === JSON.stringify(historicalRange)
    ))).toBe(true);
  });

  it("preserves the logical span while dragging and excludes zoom buttons from drag start", () => {
    vi.useFakeTimers();
    renderWorkspace(makePoints(300), "daily", "shared:drag:day");
    const area = document.querySelector(".detail-chart-area")!;
    const host = screen.getByLabelText("共享K线主图").querySelector(".detail-chart-host")!;
    Object.defineProperty(host, "clientWidth", { configurable: true, value: 1000 });
    const initialRange = chartMock.charts[0].timeScale().getVisibleLogicalRange();
    const zoomIn = screen.getByRole("button", { name: "放大K线，减少可见根数" });

    fireEvent.mouseDown(zoomIn, { button: 0, clientX: 500 });
    fireEvent.mouseMove(window, { clientX: 600 });
    expect(chartMock.charts[0].timeScale().getVisibleLogicalRange()).toEqual(initialRange);

    fireEvent.mouseDown(host, { button: 0, clientX: 500 });
    fireEvent.mouseMove(window, { clientX: 600 });
    fireEvent.mouseUp(window);
    const draggedRange = chartMock.charts[0].timeScale().getVisibleLogicalRange();
    expect(draggedRange.to - draggedRange.from).toBeCloseTo(initialRange.to - initialRange.from);
    expect(draggedRange.to).toBeLessThan(initialRange.to);

    act(() => {
      resizeObserverMock.instances.at(-1)!.trigger(host, 800);
      vi.runAllTimers();
    });
    expect(chartMock.charts[0].timeScale().getVisibleLogicalRange()).toEqual(draggedRange);
    expect(area).toBeInTheDocument();
    vi.useRealTimers();
  });

  it("cleans up observers, chart subscriptions and chart instances on unmount", () => {
    const rendered = renderWorkspace(makePoints(300), "daily", "shared:cleanup:day");
    const observer = resizeObserverMock.instances.at(-1)!;
    const charts = [...chartMock.charts];
    const candleSeries = charts[0].series[0];
    const builtInPrimitive = candleSeries.attachedPrimitives[0];

    rendered.unmount();

    expect(observer.disconnected).toBe(true);
    charts.forEach((chart) => {
      expect(chart.unsubscribeCrosshairMove).toHaveBeenCalled();
      expect(chart.timeScale().unsubscribeVisibleLogicalRangeChange).toHaveBeenCalled();
      expect(chart.remove).toHaveBeenCalledTimes(1);
    });
    expect(candleSeries.detachPrimitive).toHaveBeenCalledWith(builtInPrimitive);
    expect(candleSeries.attachedPrimitives).toHaveLength(0);
  });
});

function renderWorkspace(
  points: DetailChartPoint[],
  timeMode: "daily" | "minute" = "daily",
  dataKey = `shared:test:${timeMode}`,
) {
  return render(workspaceElement(points, timeMode, dataKey));
}

function workspaceElement(
  points: DetailChartPoint[],
  timeMode: "daily" | "minute",
  dataKey: string,
  lines = mainLines,
  primitives?: DetailChartWorkspaceProps["mainPrimitives"],
) {
  return (
    <DetailChartWorkspace
      ariaLabel="共享图表区"
      bottomBar={<span>bottom</span>}
      bottomBarAriaLabel="共享指标栏"
      dataKey={dataKey}
      mainLines={lines}
      mainPrimitives={primitives}
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
    />
  );
}

function primitiveDrawingTarget() {
  const fillText = vi.fn();
  const context = {
    beginPath: vi.fn(),
    fillText,
    lineTo: vi.fn(),
    measureText: vi.fn(() => ({ width: 40 })),
    moveTo: vi.fn(),
    restore: vi.fn(),
    save: vi.fn(),
    stroke: vi.fn(),
  };
  for (const property of [
    "fillStyle",
    "font",
    "lineCap",
    "lineJoin",
    "lineWidth",
    "strokeStyle",
    "textAlign",
    "textBaseline",
  ]) {
    Object.defineProperty(context, property, { set: vi.fn() });
  }
  return {
    fillText,
    target: {
      useMediaCoordinateSpace: (draw: (scope: unknown) => void) => draw({
        context,
        mediaSize: { height: 400, width: 600 },
      }),
    } as never,
  };
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
