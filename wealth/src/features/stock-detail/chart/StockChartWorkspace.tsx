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
import type { MarketDirection } from "../../../shared/model/market";
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

interface SharedCrosshairState {
  label: string;
  x: number;
}

interface TimeAxisMarker {
  key: string;
  label: string;
  left: number;
  tone: "year" | "month";
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
  cyan: "#30d5c8",
  amber: "#f59e0b",
  rose: "#fb7185",
  slate: "#cbd5e1",
};

const rightPriceScaleWidth = 56;
const defaultVisibleDailyBars = 90;

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
  const chartsAreaRef = useRef<HTMLDivElement | null>(null);
  const chartRefs = useRef<ChartRefs>({ kline: null, macd: null, volume: null, kdj: null });
  const [overlay, setOverlay] = useState<StockMainOverlay>("MA");
  const [hoverIndex, setHoverIndex] = useState(candles.length - 1);
  const [isChartHovering, setIsChartHovering] = useState(false);
  const [tooltipSide, setTooltipSide] = useState<"left" | "right">("right");
  const [axisFloatLabel, setAxisFloatLabel] = useState<AxisFloatLabelState | null>(null);
  const [sharedCrosshair, setSharedCrosshair] = useState<SharedCrosshairState | null>(null);
  const [timeAxisMarkers, setTimeAxisMarkers] = useState<TimeAxisMarker[]>([]);
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
    if (!chartsAreaRef.current) return;
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
    const kdjChart = createPaneChart(chartRefs.current.kdj, 112);

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
      addLine(klineChart, chartColors.blue, "ma10");
      addLine(klineChart, chartColors.purple, "ma20");
      addLine(klineChart, chartColors.cyan, "ma30");
      addLine(klineChart, chartColors.amber, "ma60");
      addLine(klineChart, chartColors.rose, "ma90");
      addLine(klineChart, chartColors.slate, "ma250");
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
      setSharedCrosshair(null);
      setIsChartHovering(false);
      isSyncingCrosshair = true;
      Object.values(syncTargets).forEach(({ chart }) => {
        chart.clearCrosshairPosition();
      });
      isSyncingCrosshair = false;
    };

    const syncCrosshairMove = (sourcePanel: ChartPanelKey, pointX: number | undefined, pointY: number | undefined, time: Time | undefined) => {
      const target = syncTargets[sourcePanel];
      updateAxisFloatLabel(sourcePanel, target.series, pointY, target.formatter);

      if (!time || pointX === undefined) {
        clearSyncedCrosshair();
        return;
      }

      const point = pointByTime.get(String(time));
      if (!point) return;
      setHoverIndex(candles.findIndex((item) => item.time === point.time));
      setIsChartHovering(true);
      setSharedCrosshair({ x: pointX, label: formatCrosshairDateLabel(point) });

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
      }
      syncCrosshairMove("kline", param.point?.x, param.point?.y, param.time as Time | undefined);
    });
    macdChart.subscribeCrosshairMove((param) => {
      if (isSyncingCrosshair) return;
      syncCrosshairMove("macd", param.point?.x, param.point?.y, param.time as Time | undefined);
    });
    volumeChart.subscribeCrosshairMove((param) => {
      if (isSyncingCrosshair) return;
      syncCrosshairMove("volume", param.point?.x, param.point?.y, param.time as Time | undefined);
    });
    kdjChart.subscribeCrosshairMove((param) => {
      if (isSyncingCrosshair) return;
      syncCrosshairMove("kdj", param.point?.x, param.point?.y, param.time as Time | undefined);
    });

    const updateTimeAxisMarkers = () => {
      if (activePeriod !== "day") {
        setTimeAxisMarkers([]);
        return;
      }
      setTimeAxisMarkers(buildDailyTimeAxisMarkers(candles, kdjChart));
    };
    let markerFrame = window.requestAnimationFrame(updateTimeAxisMarkers);
    const queueTimeAxisMarkerUpdate = () => {
      window.cancelAnimationFrame(markerFrame);
      markerFrame = window.requestAnimationFrame(updateTimeAxisMarkers);
    };

    let isSyncingVisibleRange = false;
    const applyVisibleRange = (range: { from: number; to: number }) => {
      isSyncingVisibleRange = true;
      charts.forEach((chart) => chart.timeScale().setVisibleLogicalRange(range));
      isSyncingVisibleRange = false;
      queueTimeAxisMarkerUpdate();
    };

    const visibleRangeHandlers: Array<{ chart: IChartApi; handler: () => void }> = [];
    const syncVisibleRange = (sourceChart: IChartApi) => {
      if (isSyncingVisibleRange) return;
      const visibleRange = sourceChart.timeScale().getVisibleLogicalRange();
      if (!visibleRange) return;

      isSyncingVisibleRange = true;
      charts.forEach((chart) => {
        if (chart !== sourceChart) chart.timeScale().setVisibleLogicalRange(visibleRange);
      });
      isSyncingVisibleRange = false;
      queueTimeAxisMarkerUpdate();
    };

    charts.forEach((chart) => {
      const handler = () => syncVisibleRange(chart);
      chart.timeScale().subscribeVisibleLogicalRangeChange(handler);
      visibleRangeHandlers.push({ chart, handler });
    });

    if (candles.length > 0) {
      const to = candles.length - 1;
      const from = Math.max(0, to - defaultVisibleDailyBars + 1);
      applyVisibleRange({ from, to });
    } else {
      charts.forEach((chart) => chart.timeScale().fitContent());
    }

    const chartArea = chartsAreaRef.current;
    let dragState: { pointerId: number | null; startX: number; startRange: { from: number; to: number } } | null = null;
    const startDrag = (clientX: number, target: EventTarget | null, button: number, pointerId: number | null = null) => {
      if (dragState || button !== 0) return;
      if (target instanceof Element && target.closest("button,select")) return;
      const startRange = klineChart.timeScale().getVisibleLogicalRange();
      if (!startRange) return;
      dragState = {
        pointerId,
        startRange,
        startX: clientX,
      };
    };
    const moveDrag = (clientX: number) => {
      if (!dragState) return;
      const hostWidth = Math.max(1, chartRefs.current.kline?.clientWidth ?? 1);
      const rangeWidth = dragState.startRange.to - dragState.startRange.from;
      if (rangeWidth <= 0) return;

      const deltaLogical = -((clientX - dragState.startX) * rangeWidth) / hostWidth;
      let from = dragState.startRange.from + deltaLogical;
      let to = dragState.startRange.to + deltaLogical;
      const minFrom = 0;
      const maxTo = candles.length - 1;
      if (from < minFrom) {
        to += minFrom - from;
        from = minFrom;
      }
      if (to > maxTo) {
        from -= to - maxTo;
        to = maxTo;
      }
      if (from < minFrom || to > maxTo) return;

      applyVisibleRange({ from, to });
    };
    const handlePointerDown = (event: PointerEvent) => {
      startDrag(event.clientX, event.target, event.button, event.pointerId);
      if (!dragState) return;
      chartArea.setPointerCapture(event.pointerId);
      event.preventDefault();
    };
    const handlePointerMove = (event: PointerEvent) => {
      moveDrag(event.clientX);
      if (dragState) event.preventDefault();
    };
    const clearDragState = (event: PointerEvent) => {
      if (!dragState || event.pointerId !== dragState.pointerId) return;
      if (chartArea.hasPointerCapture(event.pointerId)) chartArea.releasePointerCapture(event.pointerId);
      dragState = null;
    };
    const handleMouseDown = (event: MouseEvent) => {
      startDrag(event.clientX, event.target, event.button, null);
      if (dragState) event.preventDefault();
    };
    const handleMouseMove = (event: MouseEvent) => {
      moveDrag(event.clientX);
      if (dragState) event.preventDefault();
    };
    const handleMouseUp = () => {
      if (dragState?.pointerId === null) dragState = null;
    };
    chartArea.addEventListener("pointerdown", handlePointerDown, { capture: true });
    chartArea.addEventListener("pointermove", handlePointerMove, { capture: true });
    chartArea.addEventListener("pointerup", clearDragState, { capture: true });
    chartArea.addEventListener("pointercancel", clearDragState, { capture: true });
    chartArea.addEventListener("mousedown", handleMouseDown, { capture: true });
    window.addEventListener("mousemove", handleMouseMove, { capture: true });
    window.addEventListener("mouseup", handleMouseUp, { capture: true });

    const markerResizeObserver = new ResizeObserver(() => {
      queueTimeAxisMarkerUpdate();
    });
    markerResizeObserver.observe(chartRefs.current.kdj);

    return () => {
      window.cancelAnimationFrame(markerFrame);
      markerResizeObserver.disconnect();
      visibleRangeHandlers.forEach(({ chart, handler }) => {
        chart.timeScale().unsubscribeVisibleLogicalRangeChange(handler);
      });
      chartArea.removeEventListener("pointerdown", handlePointerDown, { capture: true });
      chartArea.removeEventListener("pointermove", handlePointerMove, { capture: true });
      chartArea.removeEventListener("pointerup", clearDragState, { capture: true });
      chartArea.removeEventListener("pointercancel", clearDragState, { capture: true });
      chartArea.removeEventListener("mousedown", handleMouseDown, { capture: true });
      window.removeEventListener("mousemove", handleMouseMove, { capture: true });
      window.removeEventListener("mouseup", handleMouseUp, { capture: true });
      charts.forEach((chart) => chart.remove());
    };
  }, [activePeriod, candleData, candles, overlay]);

  return (
    <section className="stock-detail-chart-workbench" aria-label="左侧图表区">
      <div className="stock-detail-charts-area" ref={chartsAreaRef} onMouseLeave={() => setIsChartHovering(false)}>
        {timeAxisMarkers.length > 0 ? <DailyTimeAxis markers={timeAxisMarkers} /> : null}
        {sharedCrosshair !== null ? (
          <>
            <span aria-hidden="true" className="stock-detail-crosshair-vertical" style={{ left: sharedCrosshair.x }} />
            <span className="stock-detail-crosshair-date-label" style={{ left: sharedCrosshair.x }}>
              {sharedCrosshair.label}
            </span>
          </>
        ) : null}
        <div className="stock-detail-chart-panel kline-panel" aria-label="K线主图">
          <div className="panel-header">
            <select
              aria-label="主图指标切换"
              className="overlay-select"
              value={overlay}
              onChange={(event) => {
                setOverlay(event.target.value as StockMainOverlay);
                event.currentTarget.blur();
              }}
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
          {latest && isChartHovering ? <KlineTooltip point={latest} side={tooltipSide} /> : null}
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
          metrics={latest ? [["总量", latest.volume], ["MA5", latest.ma5], ["MA10", latest.ma10]] : []}
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
      </div>
    </section>
  );
}

function formatCrosshairDateLabel(point: StockCandlePoint): string {
  return point.fullDate.replaceAll("-", "");
}

function getYearMonth(point: StockCandlePoint): { month: string; year: string } | null {
  const match = point.fullDate.match(/^(\d{4})-(\d{2})-/);
  if (!match) return null;
  return { year: match[1] ?? "", month: match[2] ?? "" };
}

function buildDailyTimeAxisMarkers(candles: StockCandlePoint[], chart: IChartApi): TimeAxisMarker[] {
  const markers: TimeAxisMarker[] = [];
  const visibleRange = chart.timeScale().getVisibleLogicalRange();
  const fromIndex = visibleRange ? Math.max(0, Math.floor(visibleRange.from)) : 0;
  const toIndex = visibleRange ? Math.min(candles.length - 1, Math.ceil(visibleRange.to)) : candles.length - 1;
  let previousMonth = "";

  for (let index = fromIndex; index <= toIndex; index += 1) {
    const point = candles[index];
    if (!point) continue;
    const yearMonth = getYearMonth(point);
    if (!yearMonth) continue;
    const isFirstPoint = index === fromIndex;
    const isNewMonth = yearMonth.month !== previousMonth;
    if (!isFirstPoint && !isNewMonth) continue;

    const coordinate = chart.timeScale().timeToCoordinate(point.time as Time);
    if (coordinate === null) continue;

    markers.push({
      key: point.time,
      label: isFirstPoint ? `${yearMonth.year}/${yearMonth.month}` : yearMonth.month,
      left: coordinate,
      tone: isFirstPoint ? "year" : "month",
    });
    previousMonth = yearMonth.month;
  }

  return markers;
}

function DailyTimeAxis({ markers }: { markers: TimeAxisMarker[] }) {
  return (
    <div aria-label="日线底部时间轴" className="stock-detail-time-axis">
      {markers.map((marker) => (
        <span className={`stock-detail-time-axis-marker ${marker.tone}`} key={marker.key} style={{ left: marker.left }}>
          {marker.label}
        </span>
      ))}
    </div>
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
      <span className="metric ma10">MID:{point.bollMiddle.toFixed(2)}</span>
      <span className="metric ma20">LOWER:{point.bollLower.toFixed(2)}</span>
      </>
    );
  }
  return (
    <>
      <span className="metric ma5">MA5:{point.ma5.toFixed(2)}</span>
      <span className="metric ma10">MA10:{point.ma10.toFixed(2)}</span>
      <span className="metric ma20">MA20:{point.ma20.toFixed(2)}</span>
      <span className="metric ma30">MA30:{point.ma30.toFixed(2)}</span>
      <span className="metric ma60">MA60:{point.ma60.toFixed(2)}</span>
      <span className="metric ma90">MA90:{point.ma90.toFixed(2)}</span>
      <span className="metric ma250">MA250:{point.ma250.toFixed(2)}</span>
    </>
  );
}

function KlineTooltip({ point, side }: { point: StockCandlePoint; side: "left" | "right" }) {
  const candleTone = directionClass(resolveValueDirection(point.changePct));
  const rows: Array<[string, string, string]> = [
    ["时间", point.fullDate.replaceAll("-", ""), "secondary"],
    ["开盘", formatTooltipNumber(point.open), candleTone],
    ["收盘", formatTooltipNumber(point.close), candleTone],
    ["最高", formatTooltipNumber(point.high), candleTone],
    ["最低", formatTooltipNumber(point.low), candleTone],
    ["涨幅", `${formatTooltipNumber(point.changePct)}%`, directionClass(resolveValueDirection(point.changePct))],
    ["振幅", `${formatTooltipNumber(point.amplitude)}%`, "secondary"],
    ["成交量", formatTooltipVolume(point.volume), "secondary"],
    ["成交额", formatTooltipAmount(point.amount), "secondary"],
    ["换手率", `${formatTooltipNumber(point.turnoverRate)}%`, "secondary"],
  ];
  return (
    <div className={`kline-tooltip ${side}`}>
      <div className="tooltip-grid">
        {rows.map(([label, value, tone]) => (
          <div className="tooltip-row" key={label}>
            <span>{label}</span>
            <b className={tone}>{value}</b>
          </div>
        ))}
      </div>
    </div>
  );
}

function resolveValueDirection(value: number): MarketDirection {
  if (!Number.isFinite(value)) return "UNKNOWN";
  if (value > 0) return "UP";
  if (value < 0) return "DOWN";
  return "FLAT";
}

function formatTooltipNumber(value: number): string {
  return value.toFixed(2);
}

function formatTooltipVolume(value: number): string {
  if (value >= 100000000) return `${(value / 100000000).toFixed(2)}亿手`;
  if (value >= 10000) return `${(value / 10000).toFixed(2)}万手`;
  return `${Math.round(value)}手`;
}

function formatTooltipAmount(value: number): string {
  if (value >= 100000) return `${(value / 100000).toFixed(2)}亿`;
  if (value >= 10) return `${(value / 10).toFixed(2)}万`;
  return value.toFixed(2);
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
