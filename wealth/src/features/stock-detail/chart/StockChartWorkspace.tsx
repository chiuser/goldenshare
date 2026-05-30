import { useEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
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

type ChartPanelKey = keyof ChartRefs;

interface AxisFloatLabelState {
  panel: ChartPanelKey;
  top: number;
  value: string;
}

interface ChartSyncTarget {
  chart: IChartApi;
  formatter: (value: number) => string;
  series: ISeriesApi<SeriesType>;
  valueOf: (point: StockCandlePoint) => number;
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

const rightPriceScaleWidth = 72;

function buildChartOptions(height: number, showTimeScale: boolean) {
  return {
    autoSize: true,
    height,
    layout: {
      attributionLogo: false,
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
      vertLine: {
        color: "rgba(247, 199, 107, 0.72)",
        labelBackgroundColor: "#1e293b",
        labelVisible: false,
        visible: false,
        style: LineStyle.Dotted,
        width: 1 as const,
      },
      horzLine: {
        color: "rgba(247, 199, 107, 0.52)",
        labelBackgroundColor: "#1e293b",
        labelVisible: false,
        style: LineStyle.Dotted,
        width: 1 as const,
      },
    },
    rightPriceScale: {
      borderColor: chartColors.axis,
      minimumWidth: rightPriceScaleWidth,
      scaleMargins: { bottom: 0.12, top: 0.12 },
    },
    timeScale: {
      borderColor: chartColors.axis,
      rightOffset: 1,
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
  const [axisFloatLabel, setAxisFloatLabel] = useState<AxisFloatLabelState | null>(null);
  const [sharedCrosshairX, setSharedCrosshairX] = useState<number | null>(null);
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
      lastValueVisible: false,
      priceLineVisible: false,
      wickDownColor: chartColors.down,
      wickUpColor: chartColors.up,
      upColor: "rgba(255, 77, 90, 0.82)",
    });
    klineSeries.setData(candleData);

    const addLine = (chart: IChartApi, color: string, key: keyof StockCandlePoint) => {
      const series = chart.addSeries(LineSeries, { color, lastValueVisible: false, lineWidth: 1, priceLineVisible: false });
      series.setData(candles.map((point) => ({ time: point.time as Time, value: Number(point[key]) })));
      return series;
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
      lastValueVisible: false,
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

    const macdBars = macdChart.addSeries(HistogramSeries, { base: 0, lastValueVisible: false, priceLineVisible: false });
    macdBars.setData(
      candles.map((point) => ({
        time: point.time as Time,
        value: point.macd,
        color: point.macd >= 0 ? "rgba(255, 77, 90, 0.64)" : "rgba(24, 208, 146, 0.64)",
      })),
    );
    addLine(macdChart, chartColors.brand, "dif");
    addLine(macdChart, chartColors.blue, "dea");

    const kdjReferenceLine = addLine(kdjChart, chartColors.brand, "k");
    addLine(kdjChart, chartColors.blue, "d");
    addLine(kdjChart, chartColors.purple, "j");
    const pointByTime = new Map(candles.map((point) => [point.time, point]));
    const syncTargets: Record<ChartPanelKey, ChartSyncTarget> = {
      kline: { chart: klineChart, formatter: formatPriceAxisValue, series: klineSeries, valueOf: (point) => point.close },
      macd: { chart: macdChart, formatter: formatSignedAxisValue, series: macdBars, valueOf: (point) => point.macd },
      volume: { chart: volumeChart, formatter: formatCompactAxisValue, series: volumeSeries, valueOf: (point) => point.volume },
      kdj: { chart: kdjChart, formatter: formatPriceAxisValue, series: kdjReferenceLine, valueOf: (point) => point.k },
    };
    let isSyncingCrosshair = false;

    const updateAxisFloatLabel = (
      panel: ChartPanelKey,
      series: ISeriesApi<SeriesType>,
      pointY: number | undefined,
      formatter: (value: number) => string,
    ) => {
      const host = chartRefs.current[panel];
      if (!host || pointY === undefined || pointY < 0 || pointY > host.clientHeight) {
        setAxisFloatLabel(null);
        return;
      }
      const price = series.coordinateToPrice(pointY);
      const numericPrice = Number(price);
      if (!Number.isFinite(numericPrice)) {
        setAxisFloatLabel(null);
        return;
      }
      const labelHeight = 20;
      const top = Math.min(Math.max(pointY, labelHeight / 2), Math.max(labelHeight / 2, host.clientHeight - labelHeight / 2));
      setAxisFloatLabel({ panel, top, value: formatter(numericPrice) });
    };

    const clearSyncedCrosshair = () => {
      setAxisFloatLabel(null);
      setSharedCrosshairX(null);
      isSyncingCrosshair = true;
      Object.values(syncTargets).forEach(({ chart }) => {
        chart.clearCrosshairPosition();
      });
      isSyncingCrosshair = false;
    };

    const syncCrosshairMove = (sourcePanel: ChartPanelKey, pointY: number | undefined, time: Time | undefined) => {
      const target = syncTargets[sourcePanel];
      updateAxisFloatLabel(sourcePanel, target.series, pointY, target.formatter);

      if (!time) {
        clearSyncedCrosshair();
        return;
      }

      const point = pointByTime.get(String(time));
      if (!point) return;
      setHoverIndex(candles.findIndex((item) => item.time === point.time));

      isSyncingCrosshair = true;
      Object.values(syncTargets).forEach(({ chart, series, valueOf }) => {
        chart.setCrosshairPosition(valueOf(point), point.time as Time, series);
      });
      isSyncingCrosshair = false;
    };

    klineChart.subscribeCrosshairMove((param) => {
      if (isSyncingCrosshair) return;
      if (param.point && chartRefs.current.kline) {
        const width = chartRefs.current.kline.clientWidth;
        setTooltipSide(param.point.x > width * 0.62 ? "left" : "right");
        setSharedCrosshairX(param.point.x);
      }
      syncCrosshairMove("kline", param.point?.y, param.time as Time | undefined);
    });
    macdChart.subscribeCrosshairMove((param) => {
      if (isSyncingCrosshair) return;
      if (param.point) setSharedCrosshairX(param.point.x);
      syncCrosshairMove("macd", param.point?.y, param.time as Time | undefined);
    });
    volumeChart.subscribeCrosshairMove((param) => {
      if (isSyncingCrosshair) return;
      if (param.point) setSharedCrosshairX(param.point.x);
      syncCrosshairMove("volume", param.point?.y, param.time as Time | undefined);
    });
    kdjChart.subscribeCrosshairMove((param) => {
      if (isSyncingCrosshair) return;
      if (param.point) setSharedCrosshairX(param.point.x);
      syncCrosshairMove("kdj", param.point?.y, param.time as Time | undefined);
    });

    charts.forEach((chart) => chart.timeScale().fitContent());

    return () => {
      charts.forEach((chart) => chart.remove());
    };
  }, [candleData, candles, overlay]);

  return (
    <section className="stock-detail-chart-workbench" aria-label="左侧图表区">
      <div className="stock-detail-charts-area">
        {sharedCrosshairX !== null ? (
          <span aria-hidden="true" className="stock-detail-crosshair-vertical" style={{ left: sharedCrosshairX }} />
        ) : null}
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
          {axisFloatLabel?.panel === "kline" ? <AxisFloatLabel label={axisFloatLabel} /> : null}
        </div>

        <IndicatorChartPanel
          hostRef={(node) => {
            chartRefs.current.macd = node;
          }}
          axisFloatLabel={axisFloatLabel?.panel === "macd" ? axisFloatLabel : null}
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
          axisFloatLabel={axisFloatLabel?.panel === "volume" ? axisFloatLabel : null}
          metrics={latest ? [["总量", latest.volume], ["MA5", latest.ma5], ["MA10", latest.ma15]] : []}
          title="成交量"
        />
        <IndicatorChartPanel
          hostRef={(node) => {
            chartRefs.current.kdj = node;
          }}
          axisFloatLabel={axisFloatLabel?.panel === "kdj" ? axisFloatLabel : null}
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

function formatPriceAxisValue(value: number): string {
  return value.toFixed(2);
}

function formatSignedAxisValue(value: number): string {
  return value.toFixed(2);
}

function formatCompactAxisValue(value: number): string {
  const absValue = Math.abs(value);
  if (absValue >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`;
  if (absValue >= 1_000) return `${(value / 1_000).toFixed(2)}K`;
  return value.toFixed(0);
}

function AxisFloatLabel({ label }: { label: AxisFloatLabelState }) {
  return (
    <span aria-label="图表Y轴浮标" className="chart-axis-float-label" style={{ top: `calc(var(--stock-detail-chart-panel-header-height) + ${label.top}px)` }}>
      {label.value}
    </span>
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
  axisFloatLabel,
  hostRef,
  metrics,
  title,
}: {
  axisFloatLabel?: AxisFloatLabelState | null;
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
      {axisFloatLabel ? <AxisFloatLabel label={axisFloatLabel} /> : null}
    </div>
  );
}
