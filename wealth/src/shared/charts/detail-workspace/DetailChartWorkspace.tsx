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

import { DetailChartPane } from "./DetailChartPane";
import {
  buildDailyTimeAxisMarkers,
  formatCompactAxisValue,
  formatCrosshairDateLabel,
  formatPriceAxisValue,
  formatShanghaiMinuteAxisLabel,
  formatSignedAxisValue,
} from "./detailChartFormatters";
import {
  buildCandlestickData,
  buildHistogramData,
  buildLineData,
  DETAIL_CHART_COLORS,
  isFiniteChartNumber,
} from "./detailChartSeries";
import type {
  DetailChartAxisFloatLabelState,
  DetailChartCrosshairPresentation,
  DetailChartPanelKey,
  DetailChartPoint,
  DetailChartTimeAxisPlacement,
  DetailChartTimeAxisMarker,
  DetailChartWorkspaceProps,
} from "./detailChartTypes";
import "./detail-chart-workspace.css";

interface ChartRefs {
  kline: HTMLDivElement | null;
  macd: HTMLDivElement | null;
  volume: HTMLDivElement | null;
  kdj: HTMLDivElement | null;
}

interface ChartSyncTarget {
  chart: IChartApi;
  formatter: (value: number) => string;
  series: ISeriesApi<SeriesType>;
  valueOf: (point: DetailChartPoint) => number | null;
}

interface SharedCrosshairState {
  label: string;
  x: number;
}

const rightPriceScaleWidth = 56;
const defaultVisibleBars = 90;
const EMPTY_MAIN_PRIMITIVES: NonNullable<DetailChartWorkspaceProps["mainPrimitives"]> = [];

export function DetailChartWorkspace({
  ariaLabel,
  bottomBar,
  bottomBarAriaLabel,
  crosshairPresentation = "synchronized-overlay",
  mainLines,
  mainPrimitives,
  panelAriaLabels,
  points,
  renderMainHeader,
  renderPanelHeader,
  renderTooltip,
  timeAxisAriaLabel,
  timeAxisPlacement = "bottom-pane",
  timeMode,
  topRightAccessory,
  visibleBars = defaultVisibleBars,
}: DetailChartWorkspaceProps) {
  const primitives = mainPrimitives ?? EMPTY_MAIN_PRIMITIVES;
  const chartsAreaRef = useRef<HTMLDivElement | null>(null);
  const chartRefs = useRef<ChartRefs>({ kline: null, macd: null, volume: null, kdj: null });
  const [hoverIndex, setHoverIndex] = useState(points.length - 1);
  const [isChartHovering, setIsChartHovering] = useState(false);
  const [tooltipSide, setTooltipSide] = useState<"left" | "right">("right");
  const [axisFloatLabel, setAxisFloatLabel] = useState<DetailChartAxisFloatLabelState | null>(null);
  const [sharedCrosshair, setSharedCrosshair] = useState<SharedCrosshairState | null>(null);
  const [timeAxisMarkers, setTimeAxisMarkers] = useState<DetailChartTimeAxisMarker[]>([]);
  const latest = points[hoverIndex] ?? points.at(-1) ?? null;
  const candleData = useMemo(() => buildCandlestickData(points), [points]);

  useEffect(() => {
    setHoverIndex(points.length - 1);
  }, [points]);

  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    if (!chartsAreaRef.current) return;
    if (!chartRefs.current.kline || !chartRefs.current.macd || !chartRefs.current.volume || !chartRefs.current.kdj) return;

    const charts: IChartApi[] = [];
    const createPaneChart = (container: HTMLDivElement, height: number, panel: DetailChartPanelKey) => {
      const showTimeScale = timeMode === "minute" && (timeAxisPlacement === "each-pane" || panel === "kdj");
      const chart = createChart(
        container,
        buildChartOptions(height, showTimeScale, timeMode, crosshairPresentation),
      );
      charts.push(chart);
      return chart;
    };

    const klineChart = createPaneChart(chartRefs.current.kline, 280, "kline");
    const macdChart = createPaneChart(chartRefs.current.macd, 112, "macd");
    const volumeChart = createPaneChart(chartRefs.current.volume, 112, "volume");
    const kdjChart = createPaneChart(chartRefs.current.kdj, 112, "kdj");
    const klineSeries = klineChart.addSeries(CandlestickSeries, {
      borderDownColor: DETAIL_CHART_COLORS.down,
      borderUpColor: DETAIL_CHART_COLORS.up,
      downColor: "rgba(24, 208, 146, 0.78)",
      lastValueVisible: false,
      priceLineVisible: false,
      wickDownColor: DETAIL_CHART_COLORS.down,
      wickUpColor: DETAIL_CHART_COLORS.up,
      upColor: "rgba(255, 77, 90, 0.82)",
    });
    klineSeries.setData(candleData);
    primitives.forEach((primitive) => klineSeries.attachPrimitive(primitive));

    const addLine = (
      chart: IChartApi,
      color: string,
      valueOf: (point: DetailChartPoint) => number | null,
    ) => {
      const series = chart.addSeries(LineSeries, {
        color,
        lastValueVisible: false,
        lineWidth: 1,
        priceLineVisible: false,
      });
      series.setData(buildLineData(points, valueOf));
      return series;
    };
    mainLines.forEach((line) => addLine(klineChart, line.color, line.valueOf));

    const volumeSeries = volumeChart.addSeries(HistogramSeries, {
      base: 0,
      lastValueVisible: false,
      priceFormat: { type: "volume" },
      priceLineVisible: false,
    });
    volumeSeries.setData(buildHistogramData(
      points,
      (point) => point.volume,
      (point) => isFiniteChartNumber(point.close) && isFiniteChartNumber(point.open) && point.close >= point.open
        ? "rgba(255, 77, 90, 0.55)"
        : "rgba(24, 208, 146, 0.55)",
    ));

    const macdBars = macdChart.addSeries(HistogramSeries, {
      base: 0,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    macdBars.setData(buildHistogramData(
      points,
      (point) => point.macd,
      (_point, value) => value >= 0 ? "rgba(255, 77, 90, 0.64)" : "rgba(24, 208, 146, 0.64)",
    ));
    addLine(macdChart, DETAIL_CHART_COLORS.brand, (point) => point.dif);
    addLine(macdChart, DETAIL_CHART_COLORS.blue, (point) => point.dea);

    const kdjReferenceLine = addLine(kdjChart, DETAIL_CHART_COLORS.brand, (point) => point.k);
    addLine(kdjChart, DETAIL_CHART_COLORS.blue, (point) => point.d);
    addLine(kdjChart, DETAIL_CHART_COLORS.purple, (point) => point.j);

    const pointByTime = new Map(points.map((point, index) => [String(point.time), { index, point }]));
    const syncTargets: Record<DetailChartPanelKey, ChartSyncTarget> = {
      kline: { chart: klineChart, formatter: formatPriceAxisValue, series: klineSeries, valueOf: (point) => point.close },
      macd: { chart: macdChart, formatter: formatSignedAxisValue, series: macdBars, valueOf: (point) => point.macd },
      volume: { chart: volumeChart, formatter: formatCompactAxisValue, series: volumeSeries, valueOf: (point) => point.volume },
      kdj: { chart: kdjChart, formatter: formatPriceAxisValue, series: kdjReferenceLine, valueOf: (point) => point.k },
    };
    let isSyncingCrosshair = false;

    const updateAxisFloatLabel = (
      panel: DetailChartPanelKey,
      series: ISeriesApi<SeriesType>,
      pointY: number | undefined,
      formatter: (value: number) => string,
    ) => {
      if (crosshairPresentation === "native-axis-labels") {
        setAxisFloatLabel(null);
        return;
      }
      const host = chartRefs.current[panel];
      if (!host || pointY === undefined || pointY < 0 || pointY > host.clientHeight) {
        setAxisFloatLabel(null);
        return;
      }
      const numericPrice = Number(series.coordinateToPrice(pointY));
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
      Object.values(syncTargets).forEach(({ chart }) => chart.clearCrosshairPosition());
      isSyncingCrosshair = false;
    };

    const syncCrosshairMove = (
      sourcePanel: DetailChartPanelKey,
      pointX: number | undefined,
      pointY: number | undefined,
      time: Time | undefined,
    ) => {
      const target = syncTargets[sourcePanel];
      updateAxisFloatLabel(sourcePanel, target.series, pointY, target.formatter);
      if (!time || pointX === undefined) {
        clearSyncedCrosshair();
        return;
      }
      const entry = pointByTime.get(String(time));
      if (!entry) {
        clearSyncedCrosshair();
        return;
      }
      setHoverIndex(entry.index);
      setIsChartHovering(true);
      setSharedCrosshair({ x: pointX, label: formatCrosshairDateLabel(entry.point, timeMode) });

      isSyncingCrosshair = true;
      Object.values(syncTargets).forEach(({ chart, series, valueOf }) => {
        const value = valueOf(entry.point);
        if (!isFiniteChartNumber(value)) {
          chart.clearCrosshairPosition();
          return;
        }
        chart.setCrosshairPosition(value, entry.point.time as Time, series);
      });
      isSyncingCrosshair = false;
    };

    const subscribeCrosshair = (panel: DetailChartPanelKey) => {
      const target = syncTargets[panel];
      const handler = (param: { point?: { x: number; y: number }; time?: Time }) => {
        if (isSyncingCrosshair) return;
        if (panel === "kline" && param.point && chartRefs.current.kline) {
          setTooltipSide(param.point.x > chartRefs.current.kline.clientWidth * 0.62 ? "left" : "right");
        }
        syncCrosshairMove(panel, param.point?.x, param.point?.y, param.time);
      };
      target.chart.subscribeCrosshairMove(handler);
      return { chart: target.chart, handler };
    };
    const crosshairHandlers = (Object.keys(syncTargets) as DetailChartPanelKey[]).map(subscribeCrosshair);

    const updateTimeAxisMarkers = () => {
      if (timeMode !== "daily") {
        setTimeAxisMarkers([]);
        return;
      }
      setTimeAxisMarkers(buildDailyTimeAxisMarkers(points, kdjChart));
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
    if (points.length > 0) {
      const to = points.length - 1;
      const from = Math.max(0, to - visibleBars + 1);
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
      dragState = { pointerId, startRange, startX: clientX };
    };
    const moveDrag = (clientX: number) => {
      if (!dragState) return;
      const hostWidth = Math.max(1, chartRefs.current.kline?.clientWidth ?? 1);
      const rangeWidth = dragState.startRange.to - dragState.startRange.from;
      if (rangeWidth <= 0) return;
      const deltaLogical = -((clientX - dragState.startX) * rangeWidth) / hostWidth;
      let from = dragState.startRange.from + deltaLogical;
      let to = dragState.startRange.to + deltaLogical;
      const maxTo = points.length - 1;
      if (from < 0) {
        to -= from;
        from = 0;
      }
      if (to > maxTo) {
        from -= to - maxTo;
        to = maxTo;
      }
      if (from < 0 || to > maxTo) return;
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
    const clearPointerDragState = (event: PointerEvent) => {
      if (!dragState || event.pointerId !== dragState.pointerId) return;
      if (chartArea.hasPointerCapture(event.pointerId)) chartArea.releasePointerCapture(event.pointerId);
      dragState = null;
    };
    const handleMouseDown = (event: MouseEvent) => {
      startDrag(event.clientX, event.target, event.button);
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
    chartArea.addEventListener("pointerup", clearPointerDragState, { capture: true });
    chartArea.addEventListener("pointercancel", clearPointerDragState, { capture: true });
    chartArea.addEventListener("mousedown", handleMouseDown, { capture: true });
    window.addEventListener("mousemove", handleMouseMove, { capture: true });
    window.addEventListener("mouseup", handleMouseUp, { capture: true });

    const markerResizeObserver = new ResizeObserver(queueTimeAxisMarkerUpdate);
    markerResizeObserver.observe(chartRefs.current.kdj);

    return () => {
      window.cancelAnimationFrame(markerFrame);
      markerResizeObserver.disconnect();
      crosshairHandlers.forEach(({ chart, handler }) => chart.unsubscribeCrosshairMove(handler));
      visibleRangeHandlers.forEach(({ chart, handler }) => chart.timeScale().unsubscribeVisibleLogicalRangeChange(handler));
      chartArea.removeEventListener("pointerdown", handlePointerDown, { capture: true });
      chartArea.removeEventListener("pointermove", handlePointerMove, { capture: true });
      chartArea.removeEventListener("pointerup", clearPointerDragState, { capture: true });
      chartArea.removeEventListener("pointercancel", clearPointerDragState, { capture: true });
      chartArea.removeEventListener("mousedown", handleMouseDown, { capture: true });
      window.removeEventListener("mousemove", handleMouseMove, { capture: true });
      window.removeEventListener("mouseup", handleMouseUp, { capture: true });
      primitives.forEach((primitive) => klineSeries.detachPrimitive(primitive));
      charts.forEach((chart) => chart.remove());
    };
  }, [candleData, crosshairPresentation, mainLines, points, primitives, timeAxisPlacement, timeMode, visibleBars]);

  return (
    <section className="detail-chart-workspace" aria-label={ariaLabel}>
      <div className="detail-chart-area" ref={chartsAreaRef} onMouseLeave={() => setIsChartHovering(false)}>
        {topRightAccessory}
        {timeAxisMarkers.length > 0 ? <DailyTimeAxis ariaLabel={timeAxisAriaLabel} markers={timeAxisMarkers} /> : null}
        {sharedCrosshair !== null ? (
          <>
            <span aria-hidden="true" className="detail-chart-crosshair-vertical" style={{ left: sharedCrosshair.x }} />
            <span className="detail-chart-crosshair-date-label" style={{ left: sharedCrosshair.x }}>
              {sharedCrosshair.label}
            </span>
          </>
        ) : null}
        <DetailChartPane
          ariaLabel={panelAriaLabels.kline}
          axisFloatLabel={axisFloatLabel?.panel === "kline" ? axisFloatLabel : null}
          className="kline-panel"
          header={renderMainHeader(latest)}
          hostRef={(node) => { chartRefs.current.kline = node; }}
          overlay={latest && isChartHovering ? renderTooltip(latest, tooltipSide) : null}
        />
        {(["macd", "volume", "kdj"] as const).map((panel) => (
          <DetailChartPane
            ariaLabel={panelAriaLabels[panel]}
            axisFloatLabel={axisFloatLabel?.panel === panel ? axisFloatLabel : null}
            header={renderPanelHeader(panel, latest)}
            hostRef={(node) => { chartRefs.current[panel] = node; }}
            key={panel}
          />
        ))}
      </div>
      {bottomBar === undefined ? (
        <div aria-hidden="true" className="detail-chart-indicator-bar detail-chart-indicator-spacer" />
      ) : (
        <div className="detail-chart-indicator-bar" aria-label={bottomBarAriaLabel}>{bottomBar}</div>
      )}
    </section>
  );
}

function buildChartOptions(
  height: number,
  showTimeScale: boolean,
  timeMode: "daily" | "minute",
  crosshairPresentation: DetailChartCrosshairPresentation,
) {
  const usesNativeAxisLabels = crosshairPresentation === "native-axis-labels";
  const crosshair = crosshairPresentation === "native-axis-labels"
    ? { mode: CrosshairMode.Normal }
    : {
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
      };
  return {
    autoSize: true,
    height,
    layout: {
      attributionLogo: false,
      background: { type: ColorType.Solid, color: "transparent" },
      fontFamily: "var(--cs-font-family-number)",
      textColor: DETAIL_CHART_COLORS.text,
    },
    localization: timeMode === "minute" && !usesNativeAxisLabels
      ? { timeFormatter: formatShanghaiMinuteAxisLabel }
      : undefined,
    grid: {
      horzLines: { color: DETAIL_CHART_COLORS.grid },
      vertLines: { color: "rgba(148, 163, 184, 0.08)" },
    },
    crosshair,
    rightPriceScale: {
      autoScale: true,
      borderColor: DETAIL_CHART_COLORS.axis,
      minimumWidth: rightPriceScaleWidth,
      scaleMargins: { bottom: 0.12, top: 0.12 },
    },
    timeScale: {
      borderColor: DETAIL_CHART_COLORS.axis,
      rightOffset: 1,
      secondsVisible: false,
      tickMarkFormatter: timeMode === "minute" && !usesNativeAxisLabels
        ? formatShanghaiMinuteAxisLabel
        : undefined,
      timeVisible: timeMode === "minute",
      visible: showTimeScale,
    },
    handleScale: false,
    handleScroll: false,
  };
}

function DailyTimeAxis({ ariaLabel, markers }: { ariaLabel: string; markers: DetailChartTimeAxisMarker[] }) {
  return (
    <div aria-label={ariaLabel} className="detail-chart-time-axis">
      {markers.map((marker) => (
        <span className={`detail-chart-time-axis-marker ${marker.tone}`} key={marker.key} style={{ left: marker.left }}>
          {marker.label}
        </span>
      ))}
    </div>
  );
}
