import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StockMinuteChartViewModel } from "../api/stockMinuteViewModelAdapter";

import { StockMinuteChartWorkspace } from "./StockMinuteChartWorkspace";

const chartMock = vi.hoisted(() => {
  const charts: Array<Record<string, any>> = [];
  const createChart = vi.fn(() => {
    let visibleRange: { from: number; to: number } | null = null;
    const visibleRangeHandlers: Array<() => void> = [];
    const crosshairHandlers: Array<(param: { point?: { x: number; y: number }; time?: number }) => void> = [];
    const timeScale = {
      fitContent: vi.fn(),
      getVisibleLogicalRange: vi.fn(() => visibleRange),
      setVisibleLogicalRange: vi.fn((range: { from: number; to: number }) => {
        visibleRange = range;
        visibleRangeHandlers.forEach((handler) => handler());
      }),
      subscribeVisibleLogicalRangeChange: vi.fn((handler: () => void) => visibleRangeHandlers.push(handler)),
      unsubscribeVisibleLogicalRangeChange: vi.fn((handler: () => void) => {
        const index = visibleRangeHandlers.indexOf(handler);
        if (index >= 0) visibleRangeHandlers.splice(index, 1);
      }),
    };
    const chart = {
      addSeries: vi.fn(() => ({ setData: vi.fn() })),
      clearCrosshairPosition: vi.fn(),
      crosshairHandlers,
      remove: vi.fn(),
      setCrosshairPosition: vi.fn(),
      subscribeCrosshairMove: vi.fn((handler: (param: { point?: { x: number; y: number }; time?: number }) => void) => crosshairHandlers.push(handler)),
      timeScale: () => timeScale,
      unsubscribeCrosshairMove: vi.fn((handler: (param: { point?: { x: number; y: number }; time?: number }) => void) => {
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
    reset: () => {
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
  createChart: chartMock.createChart,
}));

describe("StockMinuteChartWorkspace", () => {
  beforeEach(() => {
    chartMock.reset();
  });

  it("keeps null indicators out of chart values and shows indicator delay status", () => {
    const data = makeMinuteData(1);
    data.points[0]!.macdDif = null;
    data.points[0]!.macdDea = null;
    data.points[0]!.macd = null;
    data.points[0]!.kdjK = null;
    data.points[0]!.kdjD = null;
    data.points[0]!.kdjJ = null;
    data.indicatorStatus = {
      status: "DELAYED",
      expectedEndDate: "2026-07-31",
      observedEndDate: "2026-07-30",
      message: "指标尚未覆盖页面期望交易日。",
    };

    render(<StockMinuteChartWorkspace loadState="ready" data={data} />);

    expect(screen.getByText("指标尚未覆盖页面期望交易日。")).toBeInTheDocument();
    expect(screen.getByText("DIF:--")).toBeInTheDocument();
    expect(screen.getByLabelText("分钟K线")).toBeInTheDocument();
    expect(screen.getByLabelText("MACD(12,26,9)")).toBeInTheDocument();
  });

  it("keeps 500 loaded points but makes only the latest 90 visible initially", () => {
    render(<StockMinuteChartWorkspace loadState="ready" data={makeMinuteData(500)} />);

    expect(chartMock.charts).toHaveLength(4);
    chartMock.charts.forEach((chart) => {
      expect(chart.timeScale().getVisibleLogicalRange()).toEqual({ from: 410, to: 499 });
      expect(chart.timeScale().fitContent).not.toHaveBeenCalled();
    });
  });

  it("drags all minute panes through the same bounded logical range", () => {
    render(<StockMinuteChartWorkspace loadState="ready" data={makeMinuteData(500)} />);

    const chartArea = screen.getByLabelText("分钟图表区").querySelector(".stock-detail-charts-area");
    const klineHost = screen.getByLabelText("分钟K线").querySelector(".chart-host");
    expect(chartArea).not.toBeNull();
    expect(klineHost).not.toBeNull();
    Object.defineProperty(klineHost!, "clientWidth", { configurable: true, value: 500 });

    fireEvent.mouseDown(chartArea!, { button: 0, clientX: 250 });
    fireEvent.mouseMove(window, { clientX: 350 });
    fireEvent.mouseUp(window);

    const visibleRanges = chartMock.charts.map((chart) => chart.timeScale().getVisibleLogicalRange());
    expect(visibleRanges).toEqual(Array(4).fill(visibleRanges[0]));
    expect(visibleRanges[0].from).toBeLessThan(410);
    expect(visibleRanges[0].from).toBeGreaterThanOrEqual(0);
    expect(visibleRanges[0].to).toBeLessThanOrEqual(499);
  });

  it("shows a synchronized tooltip with only real minute fields", () => {
    const data = makeMinuteData(100);
    const hoveredPoint = data.points[98]!;
    hoveredPoint.macdDif = null;
    render(<StockMinuteChartWorkspace loadState="ready" data={data} />);

    const klineHost = screen.getByLabelText("分钟K线").querySelector(".chart-host");
    Object.defineProperty(klineHost!, "clientWidth", { configurable: true, value: 400 });
    act(() => {
      chartMock.charts[0].crosshairHandlers[0]({ point: { x: 300, y: 40 }, time: hoveredPoint.timestamp });
    });

    const tooltip = screen.getByLabelText("分钟K线数据提示");
    expect(tooltip).toHaveClass("left");
    expect(within(tooltip).getByText("20260731 11:08")).toBeInTheDocument();
    expect(within(tooltip).getByText("成交额")).toBeInTheDocument();
    expect(within(tooltip).getByText("--")).toBeInTheDocument();
    expect(within(tooltip).queryByText("涨幅")).not.toBeInTheDocument();
    expect(within(tooltip).queryByText("换手率")).not.toBeInTheDocument();
    expect(chartMock.charts[0].setCrosshairPosition).toHaveBeenCalled();
    expect(chartMock.charts[2].setCrosshairPosition).toHaveBeenCalled();
  });
});

function makeMinuteData(count: number): StockMinuteChartViewModel {
  return {
    tsCode: "000638.SZ",
    freq: 5,
    points: Array.from({ length: count }, (_, index) => {
      const minuteOfDay = 9 * 60 + 30 + index;
      const hour = String(Math.floor(minuteOfDay / 60)).padStart(2, "0");
      const minute = String(minuteOfDay % 60).padStart(2, "0");
      const tradeTime = `2026-07-31T${hour}:${minute}:00+08:00`;
      return {
        key: tradeTime,
        timestamp: 1_780_000_000 + index * 300,
        tradeTime,
        open: 10 + index,
        high: 11 + index,
        low: 9 + index,
        close: 10.5 + index,
        volume: 100 + index,
        amount: 1000 + index,
        macdDif: 0.1,
        macdDea: 0.2,
        macd: 0.3,
        kdjK: 20,
        kdjD: 30,
        kdjJ: 10,
      };
    }),
    dataStatus: {
      status: "READY",
      expectedEndDate: "2026-07-31",
      observedEndDate: "2026-07-31",
      message: null,
    },
    indicatorStatus: {
      status: "READY",
      expectedEndDate: "2026-07-31",
      observedEndDate: "2026-07-31",
      message: null,
    },
  };
}
