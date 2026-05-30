import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type Time,
} from "lightweight-charts";

import { directionClass } from "../../../shared/lib/marketDirection";
import type { StockCandlePoint, StockIndicatorTab, StockMainOverlay, StockPeriodKey } from "../model/stockDetailTypes";

interface StockChartWorkspaceProps {
  candles: StockCandlePoint[];
  activePeriod: StockPeriodKey;
  indicatorTabs: StockIndicatorTab[];
  onAction: (message: string) => void;
}

interface ChartRefs {
  kline: HTMLDivElement | null;
  macd: HTMLDivElement | null;
  volume: HTMLDivElement | null;
  kdj: HTMLDivElement | null;
}

const chartColors = {
  grid: "rgba(148, 163, 184, 0.14)",
  axis: "rgba(148, 163, 184, 0.32)",
  text: "#7b8aa0",
  up: "#ff4d5a",
  down: "#18d092",
  brand: "#f7c76b",
  blue: "#5aa7ff",
  purple: "#b794f4",
};

function buildChartOptions(height: number, showTimeScale: boolean) {
  return {
    autoSize: true,
    height,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      fontFamily: "var(--cs-font-family-number)",
      textColor: chartColors.text,
    },
    grid: {
      horzLines: { color: chartColors.grid },
      vertLines: { color: "rgba(148, 163, 184, 0.08)" },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: "rgba(247, 199, 107, 0.72)", labelBackgroundColor: "#1e293b" },
      horzLine: { color: "rgba(247, 199, 107, 0.52)", labelBackgroundColor: "#1e293b" },
    },
    rightPriceScale: {
      borderColor: chartColors.axis,
      scaleMargins: { bottom: 0.12, top: 0.12 },
    },
    timeScale: {
      borderColor: chartColors.axis,
      rightOffset: 4,
      timeVisible: false,
      visible: showTimeScale,
    },
    handleScale: false,
    handleScroll: false,
  };
}

export function StockChartWorkspace({ candles, activePeriod, indicatorTabs, onAction }: StockChartWorkspaceProps) {
  const chartRefs = useRef<ChartRefs>({ kline: null, macd: null, volume: null, kdj: null });
  const [overlay, setOverlay] = useState<StockMainOverlay>("MA");
  const [hoverIndex, setHoverIndex] = useState(candles.length - 1);
  const [tooltipSide, setTooltipSide] = useState<"left" | "right">("right");
  const latest = candles[hoverIndex] ?? candles.at(-1);

  const candleData = useMemo(
    () =>
      candles.map((point) => ({
        time: point.time as Time,
        open: point.open,
        high: point.high,
        low: point.low,
        close: point.close,
      })),
    [candles],
  );

  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    if (!chartRefs.current.kline || !chartRefs.current.macd || !chartRefs.current.volume || !chartRefs.current.kdj) return;

    const charts: IChartApi[] = [];
    const createPaneChart = (container: HTMLDivElement, height: number, showTimeScale = false) => {
      const chart = createChart(container, buildChartOptions(height, showTimeScale));
      charts.push(chart);
      return chart;
    };

    const klineChart = createPaneChart(chartRefs.current.kline, 280);
    const macdChart = createPaneChart(chartRefs.current.macd, 112);
    const volumeChart = createPaneChart(chartRefs.current.volume, 112);
    const kdjChart = createPaneChart(chartRefs.current.kdj, 112, true);

    const klineSeries = klineChart.addSeries(CandlestickSeries, {
      borderDownColor: chartColors.down,
      borderUpColor: chartColors.up,
      downColor: "rgba(24, 208, 146, 0.78)",
      wickDownColor: chartColors.down,
      wickUpColor: chartColors.up,
      upColor: "rgba(255, 77, 90, 0.82)",
    });
    klineSeries.setData(candleData);

    const addLine = (chart: IChartApi, color: string, key: keyof StockCandlePoint) => {
      const series = chart.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false });
      series.setData(candles.map((point) => ({ time: point.time as Time, value: Number(point[key]) })));
    };

    if (overlay === "MA") {
      addLine(klineChart, chartColors.brand, "ma5");
      addLine(klineChart, chartColors.blue, "ma15");
      addLine(klineChart, chartColors.purple, "ma30");
    } else {
      addLine(klineChart, chartColors.brand, "bollUpper");
      addLine(klineChart, chartColors.blue, "bollMiddle");
      addLine(klineChart, chartColors.purple, "bollLower");
    }

    const volumeSeries = volumeChart.addSeries(HistogramSeries, {
      base: 0,
      priceFormat: { type: "volume" },
      priceLineVisible: false,
    });
    volumeSeries.setData(
      candles.map((point) => ({
        time: point.time as Time,
        value: point.volume,
        color: point.close >= point.open ? "rgba(255, 77, 90, 0.55)" : "rgba(24, 208, 146, 0.55)",
      })),
    );

    const macdBars = macdChart.addSeries(HistogramSeries, { base: 0, priceLineVisible: false });
    macdBars.setData(
      candles.map((point) => ({
        time: point.time as Time,
        value: point.macd,
        color: point.macd >= 0 ? "rgba(255, 77, 90, 0.64)" : "rgba(24, 208, 146, 0.64)",
      })),
    );
    addLine(macdChart, chartColors.brand, "dif");
    addLine(macdChart, chartColors.blue, "dea");

    addLine(kdjChart, chartColors.brand, "k");
    addLine(kdjChart, chartColors.blue, "d");
    addLine(kdjChart, chartColors.purple, "j");

    klineChart.subscribeCrosshairMove((param) => {
      if (param.point && chartRefs.current.kline) {
        const width = chartRefs.current.kline.clientWidth;
        setTooltipSide(param.point.x > width * 0.62 ? "left" : "right");
      }
      if (!param.time) return;
      const nextIndex = candles.findIndex((point) => point.time === param.time);
      if (nextIndex >= 0) setHoverIndex(nextIndex);
    });

    charts.forEach((chart) => chart.timeScale().fitContent());

    return () => {
      charts.forEach((chart) => chart.remove());
    };
  }, [candleData, candles, overlay]);

  return (
    <section className="stock-detail-chart-workbench" aria-label="左侧图表区">
      <div className="stock-detail-charts-area">
        <div className="stock-detail-chart-panel kline-panel" aria-label="K线主图">
          <div className="panel-header">
            <select
              aria-label="主图指标切换"
              className="overlay-select"
              value={overlay}
              onChange={(event) => setOverlay(event.target.value as StockMainOverlay)}
            >
              <option value="MA">MA 均线</option>
              <option value="BOLL">BOLL 布林线</option>
            </select>
            {latest ? <KlineMetrics point={latest} overlay={overlay} /> : null}
            <button className="gear gear-btn" title="指标设置" type="button" onClick={() => onAction("指标设置暂未开通")}>
              ⚙
            </button>
          </div>
          <div
            className="chart-host"
            ref={(node) => {
              chartRefs.current.kline = node;
            }}
          />
          {latest ? <KlineTooltip point={latest} side={tooltipSide} /> : null}
        </div>

        <IndicatorChartPanel
          hostRef={(node) => {
            chartRefs.current.macd = node;
          }}
          metrics={
            latest
              ? [
                  ["MACD", latest.macd],
                  ["DIF", latest.dif],
                  ["DEA", latest.dea],
                ]
              : []
          }
          title="MACD(12,26,9)"
        />
        <IndicatorChartPanel
          hostRef={(node) => {
            chartRefs.current.volume = node;
          }}
          metrics={latest ? [["总量", latest.volume], ["MA5", latest.ma5], ["MA10", latest.ma15]] : []}
          title="成交量"
        />
        <IndicatorChartPanel
          hostRef={(node) => {
            chartRefs.current.kdj = node;
          }}
          metrics={
            latest
              ? [
                  ["K", latest.k],
                  ["D", latest.d],
                  ["J", latest.j],
                ]
              : []
          }
          title="KDJ(9,3,3)"
        />
      </div>

      <div className="stock-detail-indicator-bar" aria-label="底部指标栏">
        <div className="indicator-tabs">
          {indicatorTabs.map((tab) => (
            <button
              className={buildIndicatorClass(tab, overlay)}
              key={tab.key}
              type="button"
              onClick={() => {
                if (tab.overlay) {
                  setOverlay(tab.overlay);
                  return;
                }
                onAction(`${tab.label} 指标暂未支持`);
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="indicator-status">
          十字线：悬停图表查看｜周期：{activePeriod}｜当前：{latest?.fullDate ?? "--"}
        </div>
      </div>
    </section>
  );
}

function buildIndicatorClass(tab: StockIndicatorTab, overlay: StockMainOverlay): string {
  const isOverlayActive = tab.overlay && tab.overlay === overlay;
  const isActive = tab.active || isOverlayActive;
  return ["indicator-tab", isActive ? "active" : "", tab.supported ? "" : "unsupported"].filter(Boolean).join(" ");
}

function KlineMetrics({ point, overlay }: { point: StockCandlePoint; overlay: StockMainOverlay }) {
  if (overlay === "BOLL") {
    return (
      <>
        <span className="metric ma5">UPPER:{point.bollUpper.toFixed(2)}</span>
        <span className="metric ma15">MID:{point.bollMiddle.toFixed(2)}</span>
        <span className="metric ma30">LOWER:{point.bollLower.toFixed(2)}</span>
      </>
    );
  }
  return (
    <>
      <span className="metric ma5">MA5:{point.ma5.toFixed(2)}</span>
      <span className="metric ma15">MA15:{point.ma15.toFixed(2)}</span>
      <span className="metric ma30">MA30:{point.ma30.toFixed(2)}</span>
      <span className="metric ma60">MA60:{point.ma60.toFixed(2)}</span>
      <span className="metric ma120">MA120:{point.ma120.toFixed(2)}</span>
      <span className="metric ma250">MA250:{point.ma250.toFixed(2)}</span>
    </>
  );
}

function KlineTooltip({ point, side }: { point: StockCandlePoint; side: "left" | "right" }) {
  const direction = point.close >= point.open ? "up" : "down";
  return (
    <div className={`kline-tooltip ${side}`}>
      <div className="tooltip-title">
        <span>{point.fullDate}</span>
        <span>方案A</span>
      </div>
      <div className="tooltip-grid">
        <div className="tooltip-row">
          <span>开</span>
          <b>{point.open.toFixed(2)}</b>
        </div>
        <div className="tooltip-row">
          <span>高</span>
          <b className="up">{point.high.toFixed(2)}</b>
        </div>
        <div className="tooltip-row">
          <span>低</span>
          <b className="down">{point.low.toFixed(2)}</b>
        </div>
        <div className="tooltip-row">
          <span>收</span>
          <b className={direction}>{point.close.toFixed(2)}</b>
        </div>
      </div>
    </div>
  );
}

function IndicatorChartPanel({
  hostRef,
  metrics,
  title,
}: {
  hostRef: (node: HTMLDivElement | null) => void;
  metrics: [string, number][];
  title: string;
}) {
  return (
    <div className="stock-detail-chart-panel" aria-label={title}>
      <div className="panel-header">
        <strong>{title}</strong>
        {metrics.map(([label, value]) => (
          <span className={`metric ${directionClass(value >= 0 ? "UP" : "DOWN")}`} key={label}>
            {label}:{Math.abs(value) > 999 ? Math.round(value) : value.toFixed(2)}
          </span>
        ))}
        <button className="gear gear-btn" title="指标设置" type="button">
          ⚙
        </button>
      </div>
      <div className="chart-host" ref={hostRef} />
    </div>
  );
}
