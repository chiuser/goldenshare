import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { StockMinuteChartWorkspace } from "./StockMinuteChartWorkspace";

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: "CandlestickSeries",
  ColorType: { Solid: "Solid" },
  CrosshairMode: { Normal: 0 },
  HistogramSeries: "HistogramSeries",
  LineSeries: "LineSeries",
  createChart: () => ({
    addSeries: () => ({ setData: vi.fn() }),
    remove: vi.fn(),
    timeScale: () => ({ fitContent: vi.fn() }),
  }),
}));

describe("StockMinuteChartWorkspace", () => {
  it("keeps null indicators out of chart values and shows indicator delay status", () => {
    render(
      <StockMinuteChartWorkspace
        loadState="ready"
        data={{
          tsCode: "000638.SZ",
          freq: 5,
          points: [
            {
              key: "2026-07-31T09:30:00+08:00",
              timestamp: 1780000000,
              tradeTime: "2026-07-31T09:30:00+08:00",
              open: 1,
              high: 2,
              low: 0.5,
              close: 1.5,
              volume: 10,
              amount: 100,
              macdDif: null,
              macdDea: null,
              macd: null,
              kdjK: null,
              kdjD: null,
              kdjJ: null,
            },
          ],
          dataStatus: {
            status: "READY",
            expectedEndDate: "2026-07-31",
            observedEndDate: "2026-07-31",
            message: null,
          },
          indicatorStatus: {
            status: "DELAYED",
            expectedEndDate: "2026-07-31",
            observedEndDate: "2026-07-30",
            message: "指标尚未覆盖页面期望交易日。",
          },
        }}
      />,
    );

    expect(screen.getByText("指标尚未覆盖页面期望交易日。")).toBeInTheDocument();
    expect(screen.getByText("DIF:--")).toBeInTheDocument();
    expect(screen.getByLabelText("分钟K线")).toBeInTheDocument();
    expect(screen.getByLabelText("MACD(12,26,9)")).toBeInTheDocument();
  });
});
