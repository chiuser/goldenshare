import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type AutoscaleInfoProvider,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type SeriesType,
  type Time,
} from "lightweight-charts";

import { DetailChartPane } from "./DetailChartPane";
import { DetailChartZoomControls } from "./DetailChartZoomControls";
import { VisibleExtremaPrimitive } from "./VisibleExtremaPrimitive";
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
import {
  KDJ_RANGE_FIELDS,
  MACD_RANGE_FIELDS,
  resolveVisibleIndicatorRange,
  type DetailChartIndicatorRange,
} from "./detailChartIndicatorRange";
import type {
  DetailChartAxisFloatLabelState,
  DetailChartCrosshairPresentation,
  DetailChartHistoryViewport,
  DetailChartMacdValues,
  DetailChartPoint,
  DetailChartQuantitativeStructure,
  DetailChartTimeAxisPlacement,
  DetailChartTimeAxisMarker,
  DetailChartWorkspaceProps,
} from "./detailChartTypes";
import {
  RIGHT_PRICE_SCALE_WIDTH,
  resolveAdaptiveVisibleCount,
  resolveDetailChartPlotWidth,
  resolveInitialRange,
  resolveMainPriceScaleMargins,
  resolveRangeAfterPointCountChange,
  resolveSharedRightPriceScaleWidth,
  resolveVisibleCount,
  resolveZoomAvailability,
  resolveZoomedRange,
  resolveZoomTargetCount,
  type DetailChartLogicalRange,
} from "./detailChartViewport";
import "./detail-chart-workspace.css";

type WorkspacePanelKey = DetailChartAxisFloatLabelState["panel"];
type ChartRefs = Record<WorkspacePanelKey, HTMLDivElement | null>;

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

interface DetailChartViewportRefState {
  dataKey: string;
  lastMeasuredHostWidth: number | null;
  pointCount: number;
  range: DetailChartLogicalRange | null;
  userAdjusted: boolean;
}

interface DetailChartViewportUiState {
  dataKey: string;
  visibleCount: number;
}

interface DetailChartRuntime {
  dataKey: string;
  reportHistoryViewport?: (range: DetailChartLogicalRange) => void;
  updateHistory?: (data: DetailChartHistoryData) => void;
  applyHistoryGutter?: () => void;
  updateQuantitativeStructure?: (structure: DetailChartQuantitativeStructure) => void;
  applyRange: (range: DetailChartLogicalRange) => void;
  applyIndicatorRanges: (range: DetailChartLogicalRange) => void;
  getRange: () => DetailChartLogicalRange | null;
  queuePriceScaleAlignment: () => void;
  applyMainPriceScalePadding: (height?: number) => void;
}

interface IndicatorAxisPriceLines {
  max: IPriceLine;
  min: IPriceLine;
  zero: IPriceLine | null;
}

interface DetailChartHistoryData {
  points: DetailChartPoint[];
  candleData: ReturnType<typeof buildCandlestickData>;
  mainLines: DetailChartWorkspaceProps["mainLines"];
  primitives: NonNullable<DetailChartWorkspaceProps["mainPrimitives"]>;
}

const HISTORY_GUTTER_PX = 74;
const EMPTY_MAIN_PRIMITIVES: NonNullable<DetailChartWorkspaceProps["mainPrimitives"]> = [];

export function DetailChartWorkspace({
  ariaLabel,
  bottomBar,
  bottomBarAriaLabel,
  crosshairPresentation = "synchronized-overlay",
  dataKey,
  hiddenIndicatorPanels,
  historyPhase,
  onHistoryViewport,
  mainLines,
  mainLayerAccessory,
  mainPriceScalePaddingPx,
  mainPrimitives,
  panelAriaLabels,
  points,
  quantitativeStructure,
  renderMainHeader,
  renderPanelHeader,
  renderTooltip,
  timeAxisAriaLabel,
  timeAxisPlacement = "bottom-pane",
  timeMode,
  topRightAccessory,
}: DetailChartWorkspaceProps) {
  const primitives = mainPrimitives ?? EMPTY_MAIN_PRIMITIVES;
  const hasQuantitativeStructure = quantitativeStructure !== undefined;
  const quantitativeStructureRef = useRef(quantitativeStructure);
  quantitativeStructureRef.current = quantitativeStructure;
  const chartsAreaRef = useRef<HTMLDivElement | null>(null);
  const chartRefs = useRef<ChartRefs>({ kline: null, macd: null, quantitativeStructure: null, volume: null, kdj: null });
  const [hoverIndex, setHoverIndex] = useState(points.length - 1);
  const [isChartHovering, setIsChartHovering] = useState(false);
  const [tooltipSide, setTooltipSide] = useState<"left" | "right">("right");
  const [axisFloatLabel, setAxisFloatLabel] = useState<DetailChartAxisFloatLabelState | null>(null);
  const [sharedCrosshair, setSharedCrosshair] = useState<SharedCrosshairState | null>(null);
  const [timeAxisMarkers, setTimeAxisMarkers] = useState<DetailChartTimeAxisMarker[]>([]);
  const runtimeRef = useRef<DetailChartRuntime | null>(null);
  const mainPaddingRef = useRef(mainPriceScalePaddingPx);
  mainPaddingRef.current = mainPriceScalePaddingPx;
  const [mainPaddingUnavailable, setMainPaddingUnavailable] = useState(false);
  const viewportRef = useRef<DetailChartViewportRefState>({
    dataKey,
    lastMeasuredHostWidth: null,
    pointCount: 0,
    range: null,
    userAdjusted: false,
  });
  const [viewportUi, setViewportUi] = useState<DetailChartViewportUiState>({ dataKey, visibleCount: 0 });
  const latest = points[hoverIndex] ?? points.at(-1) ?? null;
  const candleData = useMemo(() => buildCandlestickData(points), [points]);
  const keepCharts = onHistoryViewport !== undefined;
  const dataRef = useRef<DetailChartHistoryData>({ points, candleData, mainLines, primitives });
  dataRef.current = { points, candleData, mainLines, primitives };
  const historyRef = useRef({ historyPhase, onHistoryViewport });
  historyRef.current = { historyPhase, onHistoryViewport };
  const [atHistoryEdge, setAtHistoryEdge] = useState(false);
  const zoomAvailability = viewportUi.dataKey === dataKey && viewportUi.visibleCount > 0
    ? resolveZoomAvailability(viewportUi.visibleCount, points.length)
    : { canZoomIn: false, canZoomOut: false };

  const commitViewportRange = useCallback((
    range: DetailChartLogicalRange | null,
    options: { applyToCharts?: boolean; userAdjusted?: boolean } = {},
  ) => {
    const viewport = viewportRef.current;
    viewport.range = range;
    if (options.userAdjusted) viewport.userAdjusted = true;
    const visibleCount = resolveVisibleCount(range, viewport.pointCount);
    setViewportUi((current) => current.dataKey === viewport.dataKey && current.visibleCount === visibleCount
      ? current
      : { dataKey: viewport.dataKey, visibleCount });
    if (range) {
      runtimeRef.current?.applyIndicatorRanges(range);
      if (options.applyToCharts !== false) runtimeRef.current?.applyRange(range);
      runtimeRef.current?.reportHistoryViewport?.(range);
    }
    runtimeRef.current?.queuePriceScaleAlignment();
  }, []);

  const zoom = useCallback((direction: "in" | "out") => {
    const viewport = viewportRef.current;
    if (!viewport.range || viewport.pointCount <= 0) return;
    const visibleCount = resolveVisibleCount(viewport.range, viewport.pointCount);
    const availability = resolveZoomAvailability(visibleCount, viewport.pointCount);
    if (direction === "in" ? !availability.canZoomIn : !availability.canZoomOut) return;
    const targetCount = resolveZoomTargetCount(direction, visibleCount, viewport.pointCount);
    commitViewportRange(
      resolveZoomedRange(viewport.range, targetCount, viewport.pointCount),
      { userAdjusted: true },
    );
  }, [commitViewportRange]);

  useEffect(() => {
    if (!keepCharts) setHoverIndex(points.length - 1);
  }, [keepCharts, points]);

  useEffect(() => {
    if (typeof ResizeObserver === "undefined") return;
    if (!chartsAreaRef.current) return;
    if (!chartRefs.current.kline || !chartRefs.current.macd || !chartRefs.current.volume || !chartRefs.current.kdj) return;

    const chartArea = chartsAreaRef.current;
    let { points: plottedPoints, candleData, mainLines, primitives } = dataRef.current;
    if (keepCharts) setHoverIndex(plottedPoints.length - 1);
    const charts: IChartApi[] = [];
    const createPaneChart = (container: HTMLDivElement, height: number, panel: WorkspacePanelKey) => {
      const showTimeScale = timeMode === "minute" && panel !== "quantitativeStructure"
        && (timeAxisPlacement === "each-pane" || panel === "kdj");
      const chart = createChart(
        container,
        buildChartOptions(height, showTimeScale, timeMode, crosshairPresentation, panel),
      );
      charts.push(chart);
      return chart;
    };

    const klineChart = createPaneChart(chartRefs.current.kline, 280, "kline");
    const macdChart = createPaneChart(chartRefs.current.macd, 112, "macd");
    const structureChart = hasQuantitativeStructure && chartRefs.current.quantitativeStructure
      ? createPaneChart(chartRefs.current.quantitativeStructure, 112, "quantitativeStructure")
      : null;
    const volumeChart = createPaneChart(chartRefs.current.volume, 112, "volume");
    const kdjChart = createPaneChart(chartRefs.current.kdj, 112, "kdj");
    const rightPriceScales = charts.map((chart) => chart.priceScale("right"));
    let appliedMainMargins = { top: 0.12, bottom: 0.12 };
    const applyMainPriceScalePadding = (height = chartRefs.current.kline?.clientHeight ?? 0) => {
      const margins = resolveMainPriceScaleMargins(height, mainPaddingRef.current);
      setMainPaddingUnavailable(margins === null);
      if (!margins) return;
      if (margins.top !== appliedMainMargins.top || margins.bottom !== appliedMainMargins.bottom) {
        rightPriceScales[0]!.applyOptions({ scaleMargins: margins });
        appliedMainMargins = margins;
      }
    };
    applyMainPriceScalePadding();
    let sharedRightPriceScaleWidth = RIGHT_PRICE_SCALE_WIDTH;
    let priceScaleAlignmentFrame = 0;
    chartArea.style.setProperty(
      "--detail-chart-right-price-scale-width",
      `${sharedRightPriceScaleWidth}px`,
    );
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
    const visibleExtremaPrimitive = new VisibleExtremaPrimitive(candleData);
    klineSeries.attachPrimitive(visibleExtremaPrimitive);
    primitives.forEach((primitive) => klineSeries.attachPrimitive(primitive));

    const addLine = (
      chart: IChartApi,
      color: string,
      valueOf: (point: DetailChartPoint) => number | null,
      fixedPrecision = false,
    ) => {
      const series = chart.addSeries(LineSeries, {
        color,
        lastValueVisible: false,
        lineWidth: 1,
        ...(fixedPrecision ? { priceFormat: INDICATOR_PRICE_FORMAT } : {}),
        priceLineVisible: false,
      });
      series.setData(buildLineData(plottedPoints, valueOf));
      return series;
    };
    let mainSeries = mainLines.map((line) => addLine(klineChart, line.color, line.valueOf));

    const volumeSeries = volumeChart.addSeries(HistogramSeries, {
      base: 0,
      lastValueVisible: false,
      priceFormat: { type: "volume" },
      priceLineVisible: false,
    });
    const setVolumeData = () => volumeSeries.setData(buildHistogramData(
      plottedPoints,
      (point) => point.volume,
      (point) => isFiniteChartNumber(point.close) && isFiniteChartNumber(point.open) && point.close >= point.open
        ? "rgba(255, 77, 90, 0.55)"
        : "rgba(24, 208, 146, 0.55)",
    ));

    const addMacdPane = (chart: IChartApi, valuesOf: (point: DetailChartPoint) => DetailChartMacdValues | null) => {
      const valueOf = (point: DetailChartPoint) => valuesOf(point)?.macd ?? null;
      const difOf = (point: DetailChartPoint) => valuesOf(point)?.dif ?? null;
      const deaOf = (point: DetailChartPoint) => valuesOf(point)?.dea ?? null;
      const bars = chart.addSeries(HistogramSeries, {
        base: 0,
        lastValueVisible: false,
        priceFormat: INDICATOR_PRICE_FORMAT,
        priceLineVisible: false,
      });
      const setBarData = () => bars.setData(buildHistogramData(
        plottedPoints,
        valueOf,
        (_point, value) => value >= 0 ? "rgba(255, 77, 90, 0.64)" : "rgba(24, 208, 146, 0.64)",
      ));
      setBarData();
      const dif = addLine(chart, DETAIL_CHART_COLORS.brand, difOf, true);
      const dea = addLine(chart, DETAIL_CHART_COLORS.blue, deaOf, true);
      const axisPriceLines = createIndicatorAxisPriceLines(bars, true);
      let range: DetailChartIndicatorRange | null = null;
      const autoscaleInfoProvider: AutoscaleInfoProvider = () => toAutoscaleInfo(range);
      return {
        dif,
        syncTarget: { chart, series: bars, formatter: formatSignedAxisValue, valueOf },
        setData() {
          setBarData();
          dif.setData(buildLineData(plottedPoints, difOf));
          dea.setData(buildLineData(plottedPoints, deaOf));
        },
        applyRange(visibleRange: DetailChartLogicalRange) {
          range = resolveVisibleIndicatorRange(plottedPoints, visibleRange, MACD_RANGE_FIELDS, valuesOf);
          [bars, dif, dea].forEach(series => series.applyOptions({ autoscaleInfoProvider }));
          applyIndicatorAxisPriceLines(axisPriceLines, range);
        },
      };
    };
    setVolumeData();
    const macd = addMacdPane(macdChart, (point) => point);
    let structureInput = quantitativeStructureRef.current;
    const structure = structureChart
      ? addMacdPane(structureChart, (point) => structureInput?.valuesAt(point.time) ?? null)
      : null;
    structureInput?.primitives.forEach(primitive => structure?.dif.attachPrimitive(primitive));

    const kSeries = addLine(kdjChart, DETAIL_CHART_COLORS.brand, (point) => point.k, true);
    const dSeries = addLine(kdjChart, DETAIL_CHART_COLORS.blue, (point) => point.d, true);
    const jSeries = addLine(kdjChart, DETAIL_CHART_COLORS.purple, (point) => point.j, true);
    const kdjAxisPriceLines = createIndicatorAxisPriceLines(kSeries, false);

    const indexPoints = () => new Map(plottedPoints.map((point, index) => [String(point.time), { index, point }]));
    let pointByTime = indexPoints();
    const syncTargets = new Map<WorkspacePanelKey, ChartSyncTarget>([
      ["kline", { chart: klineChart, formatter: formatPriceAxisValue, series: klineSeries, valueOf: (point) => point.close }],
      ["macd", macd.syncTarget],
      ["volume", { chart: volumeChart, formatter: formatCompactAxisValue, series: volumeSeries, valueOf: (point) => point.volume }],
      ["kdj", { chart: kdjChart, formatter: formatPriceAxisValue, series: kSeries, valueOf: (point) => point.k }],
    ]);
    if (structure) syncTargets.set("quantitativeStructure", structure.syncTarget);
    let isSyncingCrosshair = false;

    const updateAxisFloatLabel = (
      panel: WorkspacePanelKey,
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
      syncTargets.forEach(({ chart }) => chart.clearCrosshairPosition());
      isSyncingCrosshair = false;
    };

    const syncCrosshairMove = (
      sourcePanel: WorkspacePanelKey,
      target: ChartSyncTarget,
      pointX: number | undefined,
      pointY: number | undefined,
      time: Time | undefined,
    ) => {
      if (!time || pointX === undefined) {
        clearSyncedCrosshair();
        return;
      }
      const entry = pointByTime.get(String(time));
      if (!entry) {
        clearSyncedCrosshair();
        return;
      }
      if (sourcePanel === "quantitativeStructure" && !isFiniteChartNumber(target.valueOf(entry.point))) {
        setAxisFloatLabel(null);
      } else {
        updateAxisFloatLabel(sourcePanel, target.series, pointY, target.formatter);
      }
      setHoverIndex(entry.index);
      setIsChartHovering(true);
      if (crosshairPresentation === "synchronized-overlay") {
        const canonicalX = klineChart.timeScale().timeToCoordinate(entry.point.time as Time);
        setSharedCrosshair(canonicalX === null
          ? null
          : { x: canonicalX, label: formatCrosshairDateLabel(entry.point, timeMode) });
      } else {
        setSharedCrosshair(null);
      }

      isSyncingCrosshair = true;
      syncTargets.forEach(({ chart, series, valueOf }) => {
        const value = valueOf(entry.point);
        if (!isFiniteChartNumber(value)) {
          chart.clearCrosshairPosition();
          return;
        }
        chart.setCrosshairPosition(value, entry.point.time as Time, series);
      });
      isSyncingCrosshair = false;
    };

    const subscribeCrosshair = ([panel, target]: [WorkspacePanelKey, ChartSyncTarget]) => {
      const handler = (param: { point?: { x: number; y: number }; time?: Time }) => {
        if (isSyncingCrosshair) return;
        if (panel === "kline" && param.point && chartRefs.current.kline) {
          setTooltipSide(param.point.x > chartRefs.current.kline.clientWidth * 0.62 ? "left" : "right");
        }
        syncCrosshairMove(panel, target, param.point?.x, param.point?.y, param.time);
      };
      target.chart.subscribeCrosshairMove(handler);
      return { chart: target.chart, handler };
    };
    const crosshairHandlers = Array.from(syncTargets, subscribeCrosshair);

    const updateTimeAxisMarkers = () => {
      if (timeMode !== "daily") {
        setTimeAxisMarkers([]);
        return;
      }
      setTimeAxisMarkers(buildDailyTimeAxisMarkers(plottedPoints, kdjChart, keepCharts));
    };
    let markerFrame = window.requestAnimationFrame(updateTimeAxisMarkers);
    const queueTimeAxisMarkerUpdate = () => {
      window.cancelAnimationFrame(markerFrame);
      markerFrame = window.requestAnimationFrame(updateTimeAxisMarkers);
    };

    let isSyncingVisibleRange = false;
    const applyVisibleRange = (range: DetailChartLogicalRange) => {
      isSyncingVisibleRange = true;
      charts.forEach((chart) => chart.timeScale().setVisibleLogicalRange(range));
      isSyncingVisibleRange = false;
      queueTimeAxisMarkerUpdate();
    };
    let kdjRange: DetailChartIndicatorRange | null = null;
    const kdjAutoscaleProvider: AutoscaleInfoProvider = () => toAutoscaleInfo(kdjRange);
    const applyIndicatorRanges = (range: DetailChartLogicalRange) => {
      macd.applyRange(range);
      structure?.applyRange(range);
      kdjRange = resolveVisibleIndicatorRange(plottedPoints, range, KDJ_RANGE_FIELDS);
      [kSeries, dSeries, jSeries].forEach((series) => {
        series.applyOptions({ autoscaleInfoProvider: kdjAutoscaleProvider });
      });
      applyIndicatorAxisPriceLines(kdjAxisPriceLines, kdjRange);
    };
    const alignRightPriceScales = (): boolean => {
      const measuredWidth = resolveSharedRightPriceScaleWidth(
        rightPriceScales.map((scale) => scale.width()),
      );
      const nextWidth = Math.max(sharedRightPriceScaleWidth, measuredWidth);
      if (nextWidth === sharedRightPriceScaleWidth) return false;

      sharedRightPriceScaleWidth = nextWidth;
      rightPriceScales.forEach((scale) => {
        scale.applyOptions({ minimumWidth: nextWidth });
      });
      chartArea.style.setProperty(
        "--detail-chart-right-price-scale-width",
        `${nextWidth}px`,
      );

      const viewport = viewportRef.current;
      const hostWidth = chartRefs.current.kline?.clientWidth ?? 0;
      if (!viewport.userAdjusted && viewport.pointCount > 0) {
        const visibleCount = resolveAdaptiveVisibleCount(
          hostWidth,
          viewport.pointCount,
          sharedRightPriceScaleWidth,
        );
        if (visibleCount !== resolveVisibleCount(viewport.range, viewport.pointCount)) {
          const nextRange = resolveInitialRange(viewport.pointCount, visibleCount);
          if (nextRange) {
            commitViewportRange(nextRange);
            return true;
          }
        }
      }

      if (viewport.range) applyVisibleRange(viewport.range);
      return true;
    };
    const queuePriceScaleAlignment = () => {
      window.cancelAnimationFrame(priceScaleAlignmentFrame);
      priceScaleAlignmentFrame = window.requestAnimationFrame(() => {
        alignRightPriceScales();
      });
    };
    const reportViewport = (
      range: DetailChartLogicalRange,
      direction: DetailChartHistoryViewport["direction"] = "stationary",
      beyondLeft = false,
      gesture?: symbol,
    ) => {
      const first = plottedPoints[0];
      const leftIndex = Math.max(0, Math.min(plottedPoints.length - 1, Math.ceil(range.from)));
      const left = plottedPoints[leftIndex];
      if (!first || !left) return;
      setAtHistoryEdge(range.from <= 0);
      historyRef.current.onHistoryViewport?.({
        firstDate: first.fullDate, leftDate: left.fullDate, remaining: leftIndex + 1,
        direction, beyondLeft, gesture,
      });
    };
    const runtime: DetailChartRuntime = {
      dataKey,
      reportHistoryViewport: keepCharts ? reportViewport : undefined,
      updateQuantitativeStructure: structure && structureChart ? (next) => {
        const previous = structureInput;
        structureInput = next;
        if (previous?.primitives !== next.primitives) {
          previous?.primitives.forEach(primitive => structure.dif.detachPrimitive(primitive));
          next.primitives.forEach(primitive => structure.dif.attachPrimitive(primitive));
        }
        if (previous?.valuesAt !== next.valuesAt) {
          isSyncingVisibleRange = true;
          structure.setData();
          const range = viewportRef.current.range;
          if (range) {
            structure.applyRange(range);
            structureChart.timeScale().setVisibleLogicalRange(range);
          }
          isSyncingVisibleRange = false;
          queuePriceScaleAlignment();
        }
      } : undefined,
      applyRange: applyVisibleRange,
      applyIndicatorRanges,
      getRange: () => klineChart.timeScale().getVisibleLogicalRange(),
      queuePriceScaleAlignment,
      applyMainPriceScalePadding,
    };
    runtimeRef.current = runtime;
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
      commitViewportRange(visibleRange, { applyToCharts: false });
      queueTimeAxisMarkerUpdate();
    };
    charts.forEach((chart) => {
      // The structure pane can clamp its range while it has only whitespace.
      if (chart === structureChart) return;
      const handler = () => syncVisibleRange(chart);
      chart.timeScale().subscribeVisibleLogicalRangeChange(handler);
      visibleRangeHandlers.push({ chart, handler });
    });
    const previousViewport = viewportRef.current;
    const previousPointCount = previousViewport.pointCount;
    const hostWidth = chartRefs.current.kline.clientWidth;
    let initialRange: DetailChartLogicalRange | null;
    if (previousViewport.dataKey !== dataKey) {
      viewportRef.current = {
        dataKey,
        lastMeasuredHostWidth: hostWidth,
        pointCount: plottedPoints.length,
        range: null,
        userAdjusted: false,
      };
      initialRange = resolveInitialRange(
        plottedPoints.length,
        resolveAdaptiveVisibleCount(hostWidth, plottedPoints.length, sharedRightPriceScaleWidth),
      );
    } else {
      previousViewport.lastMeasuredHostWidth = hostWidth;
      previousViewport.pointCount = plottedPoints.length;
      initialRange = previousViewport.userAdjusted
        ? previousViewport.range && previousPointCount !== plottedPoints.length
          ? resolveRangeAfterPointCountChange(previousViewport.range, previousPointCount, plottedPoints.length)
          : previousViewport.range
        : resolveInitialRange(
            plottedPoints.length,
            resolveAdaptiveVisibleCount(hostWidth, plottedPoints.length, sharedRightPriceScaleWidth),
          );
      if (!initialRange && plottedPoints.length > 0) {
        initialRange = resolveInitialRange(
          plottedPoints.length,
          resolveAdaptiveVisibleCount(hostWidth, plottedPoints.length, sharedRightPriceScaleWidth),
        );
      }
    }
    if (initialRange) {
      commitViewportRange(initialRange);
    } else {
      commitViewportRange(null, { applyToCharts: false });
      charts.forEach((chart) => chart.timeScale().fitContent());
    }
    alignRightPriceScales();
    queuePriceScaleAlignment();

    let dragState: {
      pointerId: number | null;
      startX: number;
      lastX: number;
      startRange: DetailChartLogicalRange;
      gesture: symbol;
    } | null = null;
    const historyGutter = (range: DetailChartLogicalRange) => {
      const phase = historyRef.current.historyPhase;
      if (!keepCharts || (phase !== "loading" && phase !== "error")) return 0;
      const width = resolveDetailChartPlotWidth(chartRefs.current.kline?.clientWidth ?? 1, sharedRightPriceScaleWidth);
      return (range.to - range.from) * HISTORY_GUTTER_PX / width;
    };
    if (keepCharts) {
      runtime.applyHistoryGutter = () => {
        const range = viewportRef.current.range;
        if (!range || range.from > 0) return;
        const gutter = historyGutter(range);
        if (gutter === 0) return;
        const from = -gutter;
        const offset = from - range.from;
        if (offset === 0) return;
        if (dragState) {
          dragState.startRange = { from: dragState.startRange.from + offset, to: dragState.startRange.to + offset };
        }
        commitViewportRange({ from, to: range.to + offset });
      };
      runtime.updateHistory = (data) => {
        const pointsChanged = data.points !== plottedPoints;
        const linesChanged = data.mainLines !== mainLines;
        if (!pointsChanged && !linesChanged && data.primitives === primitives) return;
        const range = viewportRef.current.range;
        let offset = 0;
        isSyncingVisibleRange = true;
        if (pointsChanged) {
          const previousFirstTime = plottedPoints[0]?.time;
          offset = Math.max(0, data.points.findIndex((point) => point.time === previousFirstTime));
          plottedPoints = data.points;
          viewportRef.current.pointCount = plottedPoints.length;
          pointByTime = indexPoints();
          klineSeries.setData(data.candleData);
          visibleExtremaPrimitive.setCandles(data.candleData);
          setVolumeData();
          macd.setData();
          structure?.setData();
          kSeries.setData(buildLineData(plottedPoints, (point) => point.k));
          dSeries.setData(buildLineData(plottedPoints, (point) => point.d));
          jSeries.setData(buildLineData(plottedPoints, (point) => point.j));
          setHoverIndex(index => index + offset);
          if (dragState) {
            dragState.startRange = { from: dragState.startRange.from + offset, to: dragState.startRange.to + offset };
          }
        }
        if (linesChanged) {
          mainSeries.forEach(series => klineChart.removeSeries(series));
          mainLines = data.mainLines;
          mainSeries = mainLines.map(line => addLine(klineChart, line.color, line.valueOf));
        } else if (pointsChanged) {
          mainSeries.forEach((series, index) => series.setData(buildLineData(plottedPoints, mainLines[index]!.valueOf)));
        }
        primitives.filter(primitive => !data.primitives.includes(primitive)).forEach(primitive => klineSeries.detachPrimitive(primitive));
        data.primitives.filter(primitive => !primitives.includes(primitive)).forEach(primitive => klineSeries.attachPrimitive(primitive));
        primitives = data.primitives;
        isSyncingVisibleRange = false;
        if (range) commitViewportRange({ from: range.from + offset, to: range.to + offset });
      };
    }
    const startDrag = (clientX: number, target: EventTarget | null, button: number, pointerId: number | null = null) => {
      if (dragState || button !== 0) return;
      if (target instanceof Element && target.closest("button,select,[data-detail-chart-interactive]")) return;
      const startRange = klineChart.timeScale().getVisibleLogicalRange();
      if (!startRange) return;
      dragState = { pointerId, startRange, startX: clientX, lastX: clientX, gesture: Symbol() };
    };
    const moveDrag = (clientX: number) => {
      if (!dragState) return;
      const hostWidth = Math.max(1, chartRefs.current.kline?.clientWidth ?? 1);
      const plotWidth = resolveDetailChartPlotWidth(hostWidth, sharedRightPriceScaleWidth);
      const rangeWidth = dragState.startRange.to - dragState.startRange.from;
      if (rangeWidth <= 0) return;
      if (clientX === dragState.lastX) return;
      const direction = clientX > dragState.lastX ? "history" : "recent";
      dragState.lastX = clientX;
      const deltaLogical = -((clientX - dragState.startX) * rangeWidth) / plotWidth;
      let from = dragState.startRange.from + deltaLogical;
      let to = dragState.startRange.to + deltaLogical;
      const maxTo = plottedPoints.length - 1;
      const beyondLeft = from < 0;
      const minFrom = keepCharts
        ? Math.min(-historyGutter(dragState.startRange), dragState.startRange.from)
        : 0;
      if (from < minFrom) {
        to += minFrom - from;
        from = minFrom;
      }
      if (to > maxTo) {
        from -= to - maxTo;
        to = maxTo;
      }
      if (from < minFrom || to > maxTo) return;
      const range = { from, to };
      commitViewportRange(range, { userAdjusted: true });
      if (keepCharts) reportViewport(range, direction, beyondLeft, dragState.gesture);
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

    let resizeFrame = 0;
    let pendingKlineWidth: number | null = null;
    let pendingKlineHeight: number | null = null;
    const resizeObserver = new ResizeObserver((entries) => {
      queueTimeAxisMarkerUpdate();
      queuePriceScaleAlignment();
      const klineEntry = entries.find((entry) => entry.target === chartRefs.current.kline);
      if (klineEntry) {
        pendingKlineWidth = klineEntry.contentRect.width;
        pendingKlineHeight = klineEntry.contentRect.height;
      }
      window.cancelAnimationFrame(resizeFrame);
      resizeFrame = window.requestAnimationFrame(() => {
        if (pendingKlineWidth === null) return;
        if (pendingKlineHeight !== null) applyMainPriceScalePadding(pendingKlineHeight);
        const viewport = viewportRef.current;
        viewport.lastMeasuredHostWidth = pendingKlineWidth;
        if (viewport.dataKey === dataKey && !viewport.userAdjusted && viewport.pointCount > 0) {
          const visibleCount = resolveAdaptiveVisibleCount(
            pendingKlineWidth,
            viewport.pointCount,
            sharedRightPriceScaleWidth,
          );
          if (visibleCount !== resolveVisibleCount(viewport.range, viewport.pointCount)) {
            commitViewportRange(resolveInitialRange(viewport.pointCount, visibleCount));
          }
        }
        pendingKlineWidth = null;
        pendingKlineHeight = null;
      });
    });
    resizeObserver.observe(chartRefs.current.kline);
    resizeObserver.observe(chartRefs.current.kdj);

    return () => {
      window.cancelAnimationFrame(markerFrame);
      window.cancelAnimationFrame(priceScaleAlignmentFrame);
      window.cancelAnimationFrame(resizeFrame);
      resizeObserver.disconnect();
      if (runtimeRef.current === runtime) {
        runtimeRef.current = null;
        chartArea.style.removeProperty("--detail-chart-right-price-scale-width");
      }
      crosshairHandlers.forEach(({ chart, handler }) => chart.unsubscribeCrosshairMove(handler));
      visibleRangeHandlers.forEach(({ chart, handler }) => chart.timeScale().unsubscribeVisibleLogicalRangeChange(handler));
      chartArea.removeEventListener("pointerdown", handlePointerDown, { capture: true });
      chartArea.removeEventListener("pointermove", handlePointerMove, { capture: true });
      chartArea.removeEventListener("pointerup", clearPointerDragState, { capture: true });
      chartArea.removeEventListener("pointercancel", clearPointerDragState, { capture: true });
      chartArea.removeEventListener("mousedown", handleMouseDown, { capture: true });
      window.removeEventListener("mousemove", handleMouseMove, { capture: true });
      window.removeEventListener("mouseup", handleMouseUp, { capture: true });
      klineSeries.detachPrimitive(visibleExtremaPrimitive);
      primitives.forEach((primitive) => klineSeries.detachPrimitive(primitive));
      structureInput?.primitives.forEach(primitive => structure?.dif.detachPrimitive(primitive));
      charts.forEach((chart) => chart.remove());
    };
  }, [commitViewportRange, crosshairPresentation, dataKey, hasQuantitativeStructure, keepCharts,
    keepCharts ? null : candleData,
    keepCharts ? null : mainLines, keepCharts ? null : points, keepCharts ? null : primitives, timeAxisPlacement, timeMode]);

  useLayoutEffect(() => {
    const runtime = runtimeRef.current;
    if (runtime?.dataKey !== dataKey) return;
    runtime.updateHistory?.(dataRef.current);
    runtime.applyHistoryGutter?.();
  }, [dataKey, historyPhase, points, mainLines, primitives]);

  useEffect(() => {
    runtimeRef.current?.applyMainPriceScalePadding();
  }, [mainPriceScalePaddingPx?.top, mainPriceScalePaddingPx?.bottom]);

  const structureValuesAt = quantitativeStructure?.valuesAt;
  const structurePrimitives = quantitativeStructure?.primitives;
  useEffect(() => {
    const input = quantitativeStructureRef.current;
    if (input) runtimeRef.current?.updateQuantitativeStructure?.(input);
  }, [structureValuesAt, structurePrimitives]);

  return (
    <section className="detail-chart-workspace" aria-label={ariaLabel}>
      <div className="detail-chart-area" data-time-mode={timeMode} ref={chartsAreaRef} onMouseLeave={() => setIsChartHovering(false)}>
        {topRightAccessory}
        {timeAxisMarkers.length > 0 ? <DailyTimeAxis ariaLabel={timeAxisAriaLabel} markers={timeAxisMarkers} /> : null}
        {crosshairPresentation === "synchronized-overlay" && sharedCrosshair !== null ? (
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
          overlay={(
            <>
              {mainLayerAccessory}
              {keepCharts && atHistoryEdge && historyPhase && historyPhase !== "idle" ? (
                <span className={`detail-chart-history-edge ${historyPhase}`} role="status">
                  {historyPhase === "loading" ? "加载中" : "加载失败"}
                </span>
              ) : null}
              {mainPaddingUnavailable ? <span role="status" style={{ position: "absolute", left: 8,
                top: "calc(var(--detail-chart-panel-header-height, 28px) + 8px)" }}>图表空间不足</span> : null}
              {latest && isChartHovering ? renderTooltip(latest, tooltipSide) : null}
              {points.length > 0 ? (
                <DetailChartZoomControls
                  canZoomIn={zoomAvailability.canZoomIn}
                  canZoomOut={zoomAvailability.canZoomOut}
                  onZoomIn={() => zoom("in")}
                  onZoomOut={() => zoom("out")}
                />
              ) : null}
            </>
          )}
        />
        {(["macd", "quantitativeStructure", "volume", "kdj"] as const).map((panel) => panel === "quantitativeStructure" ? (
          quantitativeStructure ? <DetailChartPane
            ariaLabel={quantitativeStructure.ariaLabel}
            axisFloatLabel={axisFloatLabel?.panel === panel ? axisFloatLabel : null}
            className="quantitative-structure-panel"
            header={quantitativeStructure.renderHeader(latest ? quantitativeStructure.valuesAt(latest.time) : null)}
            hidden={hiddenIndicatorPanels?.has(panel)}
            hostRef={(node) => { chartRefs.current.quantitativeStructure = node; }}
            key={panel}
          /> : null
        ) : (
          <DetailChartPane
            ariaLabel={panelAriaLabels[panel]}
            axisFloatLabel={axisFloatLabel?.panel === panel ? axisFloatLabel : null}
            className={`${panel}-panel`}
            header={renderPanelHeader(panel, latest)}
            hidden={hiddenIndicatorPanels?.has(panel)}
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
  panel: WorkspacePanelKey,
) {
  const isIndicatorPanel = panel === "macd" || panel === "quantitativeStructure" || panel === "kdj";
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
    localization: timeMode === "minute"
      ? { timeFormatter: formatShanghaiMinuteAxisLabel }
      : undefined,
    grid: {
      horzLines: { color: DETAIL_CHART_COLORS.grid, visible: !isIndicatorPanel },
      vertLines: { color: "rgba(148, 163, 184, 0.08)" },
    },
    crosshair,
    rightPriceScale: {
      autoScale: true,
      borderColor: DETAIL_CHART_COLORS.axis,
      minimumWidth: RIGHT_PRICE_SCALE_WIDTH,
      scaleMargins: isIndicatorPanel
        ? { bottom: 0, top: 0 }
        : { bottom: 0.12, top: 0.12 },
    },
    timeScale: {
      borderColor: DETAIL_CHART_COLORS.axis,
      rightOffset: 1,
      secondsVisible: false,
      tickMarkFormatter: timeMode === "minute"
        ? formatShanghaiMinuteAxisLabel
        : undefined,
      timeVisible: timeMode === "minute",
      visible: showTimeScale,
    },
    handleScale: false,
    handleScroll: false,
  };
}

const INDICATOR_AXIS_VALUE_WIDTH = 8;
const INDICATOR_BOUNDARY_LINE_COLOR = "rgba(148, 163, 184, 0.28)";
const INDICATOR_PRICE_FORMAT = {
  formatter: (value: number) => value.toFixed(2).padStart(INDICATOR_AXIS_VALUE_WIDTH, "\u2007"),
  minMove: 0.01,
  tickmarksFormatter: (values: number[]) => values.map(() => ""),
  type: "custom",
} as const;

function createIndicatorAxisPriceLines(
  referenceSeries: ISeriesApi<SeriesType>,
  includeZeroLine: boolean,
): IndicatorAxisPriceLines {
  const hiddenLine = {
    axisLabelTextColor: "#f8fafc",
    axisLabelVisible: false,
    lineStyle: LineStyle.Dotted,
    lineVisible: false,
    lineWidth: 1 as const,
    price: 0,
    title: "",
  };
  return {
    max: referenceSeries.createPriceLine({
      ...hiddenLine,
      axisLabelColor: DETAIL_CHART_COLORS.up,
      color: INDICATOR_BOUNDARY_LINE_COLOR,
      lineStyle: LineStyle.Solid,
    }),
    min: referenceSeries.createPriceLine({
      ...hiddenLine,
      axisLabelColor: DETAIL_CHART_COLORS.down,
      color: INDICATOR_BOUNDARY_LINE_COLOR,
      lineStyle: LineStyle.Solid,
    }),
    zero: includeZeroLine
      ? referenceSeries.createPriceLine({
          ...hiddenLine,
          axisLabelColor: DETAIL_CHART_COLORS.axis,
          color: DETAIL_CHART_COLORS.axis,
        })
      : null,
  };
}

function applyIndicatorAxisPriceLines(
  lines: IndicatorAxisPriceLines,
  range: DetailChartIndicatorRange | null,
) {
  lines.max.applyOptions({
    axisLabelVisible: range !== null,
    lineVisible: range !== null,
    price: range?.dataMax ?? 0,
  });
  lines.min.applyOptions({
    axisLabelVisible: range !== null && !range.isDegenerate,
    lineVisible: range !== null && !range.isDegenerate,
    price: range?.dataMin ?? 0,
  });
  const crossesZero = range !== null && range.dataMin < 0 && range.dataMax > 0;
  lines.zero?.applyOptions({
    axisLabelVisible: crossesZero,
    lineVisible: crossesZero,
    price: 0,
  });
}

function toAutoscaleInfo(range: DetailChartIndicatorRange | null) {
  return range
    ? { priceRange: { maxValue: range.domainMax, minValue: range.domainMin } }
    : null;
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
