import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StockCandlePoint, StockIndicatorTab } from "../model/stockDetailTypes";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import { StockChartWorkspace } from "./StockChartWorkspace";
import { idleNineTurnLayer } from "../../nine-turn/model/nineTurnAdapter";

const chartMock = vi.hoisted(() => {
  const charts: Array<Record<string, any>> = [];
  const createChart = vi.fn(() => {
    const series: Array<Record<string, any>> = [];
    let visibleRange: { from: number; to: number } | null = null;
    const visibleRangeHandlers: Array<() => void> = [];
    const crosshairHandlers: Array<(param: { point?: { x: number; y: number }; time?: string }) => void> = [];
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
        const addedSeries = {
          applyOptions: vi.fn(),
          attachPrimitive: vi.fn(),
          coordinateToPrice: vi.fn(() => 12.34),
          createPriceLine: vi.fn(() => ({ applyOptions: vi.fn() })),
          detachPrimitive: vi.fn(),
          setData: vi.fn(),
        };
        series.push(addedSeries);
        return addedSeries;
      }),
      clearCrosshairPosition: vi.fn(),
      crosshairHandlers,
      remove: vi.fn(),
      series,
      setCrosshairPosition: vi.fn(),
      subscribeCrosshairMove: vi.fn((handler: (param: { point?: { x: number; y: number }; time?: string }) => void) => {
        crosshairHandlers.push(handler);
      }),
      timeScale: () => timeScale,
      unsubscribeCrosshairMove: vi.fn((handler: (param: { point?: { x: number; y: number }; time?: string }) => void) => {
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

const indicatorTabs: StockIndicatorTab[] = [
  { key: "MA", label: "均线", active: true, supported: true, overlay: "MA" },
  { key: "BOLL", label: "BOLL", active: false, supported: true, overlay: "BOLL" },
  { key: "MACD", label: "MACD", active: false, supported: true },
];

describe("StockChartWorkspace shared adapter", () => {
  beforeEach(() => chartMock.reset());

  it("preserves the stock four-pane, 120-bar, overlay and tooltip behavior", () => {
    const candles = makeCandles(300);
    const onAction = vi.fn();
    render(
      <StockChartWorkspace
        candles={candles}
        indicatorTabs={indicatorTabs}
        nineTurnLayer={idleNineTurnLayer("day")}
        onNineTurnRetry={vi.fn()}
        onAction={onAction}
        tsCode="000001.SZ"
      />,
    );

    expect(chartMock.charts).toHaveLength(4);
    chartMock.charts.forEach((chart) => {
      expect(chart.timeScale().getVisibleLogicalRange()).toEqual({ from: 180, to: 299 });
    });
    expect(screen.getByLabelText("K线主图")).toBeInTheDocument();
    expect(screen.getByLabelText("MACD(12,26,9)")).toBeInTheDocument();
    expect(screen.getByLabelText("成交量")).toBeInTheDocument();
    expect(screen.getByLabelText("KDJ(9,3,3)")).toBeInTheDocument();
    expect(screen.getByText("MA250:19.99")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("主图指标切换"), { target: { value: "BOLL" } });
    expect(screen.getByText("UPPER:22.99")).toBeInTheDocument();
    const activeCharts = chartMock.charts.slice(-4);

    const klinePanel = screen.getByLabelText("K线主图");
    const klineHost = klinePanel.querySelector(".detail-chart-host");
    Object.defineProperty(klineHost!, "clientWidth", { configurable: true, value: 400 });
    act(() => {
      activeCharts[0].crosshairHandlers[0]({ point: { x: 300, y: 40 }, time: candles[298]!.time });
    });

    const tooltip = within(klinePanel).getByText("时间").closest(".detail-chart-tooltip");
    expect(tooltip).toHaveClass("left");
    expect(within(tooltip as HTMLElement).getByText(candles[298]!.fullDate.replaceAll("-", ""))).toBeInTheDocument();
    expect(activeCharts[0].setCrosshairPosition).toHaveBeenCalled();
    expect(activeCharts[3].setCrosshairPosition).toHaveBeenCalled();
  });

  it("updates nine-turn markers without rebuilding the shared chart", () => {
    const candles = makeCandles(30);
    const rendered = render(
      <StockChartWorkspace
        candles={candles}
        indicatorTabs={indicatorTabs}
        nineTurnLayer={idleNineTurnLayer("day")}
        onNineTurnRetry={vi.fn()}
        onAction={vi.fn()}
        tsCode="000001.SZ"
      />,
    );
    expect(chartMock.createChart).toHaveBeenCalledTimes(4);

    rendered.rerender(
      <StockChartWorkspace
        candles={candles}
        indicatorTabs={indicatorTabs}
        nineTurnLayer={readyNineTurnLayer(candles.at(-1)!.fullDate)}
        onNineTurnRetry={vi.fn()}
        onAction={vi.fn()}
        tsCode="000001.SZ"
      />,
    );

    expect(chartMock.createChart).toHaveBeenCalledTimes(4);
  });

  it("renders unavailable daily moving averages as whitespace and dash", () => {
    const candles = makeCandles(10);
    candles.forEach((candle, index) => {
      candle.ma5 = index < 4 ? null : 17 + index / 100;
      candle.ma250 = null;
    });

    render(
      <StockChartWorkspace
        candles={candles}
        indicatorTabs={indicatorTabs}
        nineTurnLayer={idleNineTurnLayer("day")}
        onNineTurnRetry={vi.fn()}
        onAction={vi.fn()}
        tsCode="688635.SH"
      />,
    );

    const ma5Data = chartMock.charts[0].series[1].setData.mock.calls[0][0];
    const ma250Data = chartMock.charts[0].series[7].setData.mock.calls[0][0];
    expect(ma5Data.slice(0, 5)).toEqual([
      { time: candles[0]!.time },
      { time: candles[1]!.time },
      { time: candles[2]!.time },
      { time: candles[3]!.time },
      { time: candles[4]!.time, value: candles[4]!.ma5 },
    ]);
    expect(ma5Data.some((item: { value?: number }) => item.value === 0)).toBe(false);
    expect(ma250Data.every((item: { value?: number }) => !("value" in item))).toBe(true);
    expect(screen.getByText("MA250:--")).toBeInTheDocument();

    act(() => {
      chartMock.charts[0].crosshairHandlers[0]({ point: { x: 100, y: 40 }, time: candles[0]!.time });
    });
    const klinePanel = screen.getByLabelText("K线主图");
    expect(within(klinePanel).getByText("MA5:--")).toBeInTheDocument();
    expect(within(klinePanel).queryByText("MA5:0.00")).not.toBeInTheDocument();
  });
});

function readyNineTurnLayer(tradeDate: string): NineTurnLayerViewModel {
  return {
    canRetry: false,
    data: null,
    errorCode: null,
    markers: [{
      completed: true,
      direction: "UP",
      sequenceNumber: 9,
      tradeDate,
      tradeTime: null,
    }],
    message: null,
    period: "day",
    phase: "READY",
  };
}

function makeCandles(count: number): StockCandlePoint[] {
  return Array.from({ length: count }, (_, index) => {
    const time = new Date(Date.UTC(2026, 0, 1 + index)).toISOString().slice(0, 10);
    return {
      time,
      fullDate: time,
      open: 18 + index / 100,
      high: 19 + index / 100,
      low: 17 + index / 100,
      close: 18.5 + index / 100,
      preClose: 18.4 + index / 100,
      changePct: 0.5,
      amplitude: 1.2,
      volume: 100_000 + index,
      volumeDisplay: "10.00万",
      amount: 1_000_000 + index,
      turnoverRate: 1.3,
      volumeRatio: 1.1,
      ma5: 17 + index / 100,
      ma10: 17 + index / 100,
      ma20: 17 + index / 100,
      ma30: 17 + index / 100,
      ma60: 17 + index / 100,
      ma90: 17 + index / 100,
      ma250: 17 + index / 100,
      bollUpper: 20 + index / 100,
      bollMiddle: 18 + index / 100,
      bollLower: 16 + index / 100,
      macd: 0.3,
      dif: 0.1,
      dea: 0.2,
      k: 44,
      d: 55,
      j: 66,
    };
  });
}
