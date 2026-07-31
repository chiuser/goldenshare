import { type ReactNode, useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";

import { directionClass } from "../../../shared/lib/marketDirection";
import type { MarketDirection } from "../../../shared/model/market";
import type { StockMinuteChartPoint, StockMinuteChartViewModel } from "../api/stockMinuteViewModelAdapter";

interface StockMinuteChartWorkspaceProps {
  data: StockMinuteChartViewModel | null;
  loadState: "idle" | "loading" | "ready" | "error";
  errorMessage?: string;
}

interface MinuteChartRefs {
  kline: HTMLDivElement | null;
  macd: HTMLDivElement | null;
  volume: HTMLDivElement | null;
  kdj: HTMLDivElement | null;
}

type MinuteChartPanelKey = keyof MinuteChartRefs;

interface MinuteChartSyncTarget {
  chart: IChartApi;
  series: ISeriesApi<SeriesType>;
  valueOf: (point: StockMinuteChartPoint) => number | null;
}

interface SharedCrosshairState {
  label: string;
  x: number;
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

const minuteChartHeight = 112;
const defaultVisibleMinuteBars = 90;

export function StockMinuteChartWorkspace({ data, loadState, errorMessage }: StockMinuteChartWorkspaceProps) {
  const chartsAreaRef = useRef<HTMLDivElement | null>(null);
  const chartRefs = useRef<MinuteChartRefs>({ kline: null, macd: null, volume: null, kdj: null });
  const [hoverIndex, setHoverIndex] = useState(Math.max(0, (data?.points.length ?? 1) - 1));
  const [isChartHovering, setIsChartHovering] = useState(false);
  const [tooltipSide, setTooltipSide] = useState<"left" | "right">("right");
  const [sharedCrosshair, setSharedCrosshair] = useState<SharedCrosshairState | null>(null);

  useEffect(() => {
    if (!data || data.points.length === 0) return;
    const chartArea = chartsAreaRef.current;
    if (!chartArea || Object.values(chartRefs.current).some((host) => host === null)) return;

    const charts: IChartApi[] = [];
    const createPane = (host: HTMLDivElement, height: number) => {
      const chart = createChart(host, buildMinuteChartOptions(height));
      charts.push(chart);
      return chart;
    };
    const klineChart = createPane(chartRefs.current.kline!, 280);
    const macdChart = createPane(chartRefs.current.macd!, minuteChartHeight);
    const volumeChart = createPane(chartRefs.current.volume!, minuteChartHeight);
    const kdjChart = createPane(chartRefs.current.kdj!, minuteChartHeight);
    const candleData = data.points.map((point) => ({
      time: point.timestamp as UTCTimestamp,
      open: point.open,
      high: point.high,
      low: point.low,
      close: point.close,
    }));

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

    const volumeSeries = volumeChart.addSeries(HistogramSeries, {
      base: 0,
      lastValueVisible: false,
      priceFormat: { type: "volume" },
      priceLineVisible: false,
    });
    volumeSeries.setData(
      data.points.map((point) => ({
        time: point.timestamp as UTCTimestamp,
        value: point.volume,
        color: point.close >= point.open ? "rgba(255, 77, 90, 0.55)" : "rgba(24, 208, 146, 0.55)",
      })),
    );

    const addNullableLine = (chart: IChartApi, color: string, key: "macdDif" | "macdDea" | "kdjK" | "kdjD" | "kdjJ") => {
      const series = chart.addSeries(LineSeries, {
        color,
        lastValueVisible: false,
        lineWidth: 1,
        priceLineVisible: false,
      });
      series.setData(
        data.points.flatMap((point) => {
          const value = point[key];
          return value === null || !Number.isFinite(value)
            ? []
            : [{ time: point.timestamp as UTCTimestamp, value }];
        }),
      );
      return series;
    };

    const macdBars = macdChart.addSeries(HistogramSeries, {
      base: 0,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    macdBars.setData(
      data.points.flatMap((point) => {
        const value = point.macd;
        return value === null || !Number.isFinite(value)
          ? []
          : [{ time: point.timestamp as UTCTimestamp, value, color: value >= 0 ? "rgba(255, 77, 90, 0.64)" : "rgba(24, 208, 146, 0.64)" }];
      }),
    );
    addNullableLine(macdChart, chartColors.brand, "macdDif");
    addNullableLine(macdChart, chartColors.blue, "macdDea");
    const kdjKSeries = addNullableLine(kdjChart, chartColors.brand, "kdjK");
    addNullableLine(kdjChart, chartColors.blue, "kdjD");
    addNullableLine(kdjChart, chartColors.purple, "kdjJ");

    const pointByTimestamp = new Map(data.points.map((point, index) => [String(point.timestamp), { point, index }]));
    const syncTargets: Record<MinuteChartPanelKey, MinuteChartSyncTarget> = {
      kline: { chart: klineChart, series: klineSeries, valueOf: (point) => point.close },
      macd: { chart: macdChart, series: macdBars, valueOf: (point) => point.macd },
      volume: { chart: volumeChart, series: volumeSeries, valueOf: (point) => point.volume },
      kdj: { chart: kdjChart, series: kdjKSeries, valueOf: (point) => point.kdjK },
    };
    let isSyncingCrosshair = false;

    const clearSyncedCrosshair = () => {
      setIsChartHovering(false);
      setSharedCrosshair(null);
      isSyncingCrosshair = true;
      Object.values(syncTargets).forEach(({ chart }) => chart.clearCrosshairPosition());
      isSyncingCrosshair = false;
    };

    const syncCrosshairMove = (pointX: number | undefined, time: Time | undefined) => {
      if (!time || pointX === undefined) {
        clearSyncedCrosshair();
        return;
      }
      const entry = pointByTimestamp.get(String(time));
      if (!entry) {
        clearSyncedCrosshair();
        return;
      }

      setHoverIndex(entry.index);
      setIsChartHovering(true);
      setSharedCrosshair({ x: pointX, label: formatMinuteTradeTime(entry.point.tradeTime) });

      isSyncingCrosshair = true;
      Object.values(syncTargets).forEach(({ chart, series, valueOf }) => {
        const value = valueOf(entry.point);
        if (value === null || !Number.isFinite(value)) {
          chart.clearCrosshairPosition();
          return;
        }
        chart.setCrosshairPosition(value, entry.point.timestamp as Time, series);
      });
      isSyncingCrosshair = false;
    };

    const subscribeCrosshair = (panel: MinuteChartPanelKey) => {
      const target = syncTargets[panel];
      const handler = (param: { point?: { x: number }; time?: Time }) => {
        if (isSyncingCrosshair) return;
        if (panel === "kline" && param.point && chartRefs.current.kline) {
          setTooltipSide(param.point.x > chartRefs.current.kline.clientWidth * 0.62 ? "left" : "right");
        }
        syncCrosshairMove(param.point?.x, param.time);
      };
      target.chart.subscribeCrosshairMove(handler);
      return { chart: target.chart, handler };
    };
    const crosshairHandlers = (Object.keys(syncTargets) as MinuteChartPanelKey[]).map(subscribeCrosshair);

    let isSyncingVisibleRange = false;
    const applyVisibleRange = (range: { from: number; to: number }) => {
      isSyncingVisibleRange = true;
      charts.forEach((chart) => chart.timeScale().setVisibleLogicalRange(range));
      isSyncingVisibleRange = false;
    };
    const visibleRangeHandlers: Array<{ chart: IChartApi; handler: () => void }> = [];
    const syncVisibleRange = (sourceChart: IChartApi) => {
      if (isSyncingVisibleRange) return;
      const visibleRange = sourceChart.timeScale().getVisibleLogicalRange();
      if (!visibleRange) return;
      applyVisibleRange(visibleRange);
    };
    charts.forEach((chart) => {
      const handler = () => syncVisibleRange(chart);
      chart.timeScale().subscribeVisibleLogicalRangeChange(handler);
      visibleRangeHandlers.push({ chart, handler });
    });

    const initialTo = data.points.length - 1;
    const initialFrom = Math.max(0, initialTo - defaultVisibleMinuteBars + 1);
    setHoverIndex(initialTo);
    applyVisibleRange({ from: initialFrom, to: initialTo });

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
      const maxTo = data.points.length - 1;
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
    chartArea.addEventListener("mouseleave", clearSyncedCrosshair);
    window.addEventListener("mousemove", handleMouseMove, { capture: true });
    window.addEventListener("mouseup", handleMouseUp, { capture: true });

    return () => {
      crosshairHandlers.forEach(({ chart, handler }) => chart.unsubscribeCrosshairMove(handler));
      visibleRangeHandlers.forEach(({ chart, handler }) => chart.timeScale().unsubscribeVisibleLogicalRangeChange(handler));
      chartArea.removeEventListener("pointerdown", handlePointerDown, { capture: true });
      chartArea.removeEventListener("pointermove", handlePointerMove, { capture: true });
      chartArea.removeEventListener("pointerup", clearPointerDragState, { capture: true });
      chartArea.removeEventListener("pointercancel", clearPointerDragState, { capture: true });
      chartArea.removeEventListener("mousedown", handleMouseDown, { capture: true });
      chartArea.removeEventListener("mouseleave", clearSyncedCrosshair);
      window.removeEventListener("mousemove", handleMouseMove, { capture: true });
      window.removeEventListener("mouseup", handleMouseUp, { capture: true });
      charts.forEach((chart) => chart.remove());
    };
  }, [data]);

  const latest = data?.points[hoverIndex] ?? data?.points.at(-1);
  const status = data ? resolveMinuteStatus(data) : loadState === "error" ? "ERROR" : loadState === "loading" ? "LOADING" : "EMPTY";
  const statusMessage = errorMessage ?? resolveMinuteStatusMessage(data, status);

  if (!data || data.points.length === 0) {
    return (
      <section className="stock-detail-chart-workbench stock-minute-chart-workbench" aria-label="分钟图表区">
        <div className="stock-minute-chart-empty" role="status">
          <strong>{statusMessage}</strong>
          <span>freq={data?.freq ?? "-"}，dataStatus={status}</span>
        </div>
      </section>
    );
  }

  return (
    <section className="stock-detail-chart-workbench stock-minute-chart-workbench" aria-label="分钟图表区">
      <div className="stock-detail-charts-area" ref={chartsAreaRef}>
        <div className="stock-minute-chart-status" role="status">
          <span>{statusMessage}</span>
          <span>freq={data.freq}</span>
        </div>
        {sharedCrosshair !== null ? (
          <>
            <span aria-hidden="true" className="stock-detail-crosshair-vertical" style={{ left: sharedCrosshair.x }} />
            <span className="stock-detail-crosshair-date-label" style={{ left: sharedCrosshair.x }}>
              {sharedCrosshair.label}
            </span>
          </>
        ) : null}
        <MinutePanel
          title="分钟K线"
          hostRef={(node) => (chartRefs.current.kline = node)}
          metrics={latest ? [["收盘", formatNumber(latest.close)]] : []}
          overlay={latest && isChartHovering ? <MinuteKlineTooltip point={latest} side={tooltipSide} /> : null}
        />
        <MinutePanel
          title="MACD(12,26,9)"
          hostRef={(node) => (chartRefs.current.macd = node)}
          metrics={latest ? [["DIF", formatNullable(latest.macdDif)], ["DEA", formatNullable(latest.macdDea)], ["MACD", formatNullable(latest.macd)]] : []}
        />
        <MinutePanel title="成交量" hostRef={(node) => (chartRefs.current.volume = node)} metrics={latest ? [["量", formatNumber(latest.volume)]] : []} />
        <MinutePanel
          title="KDJ(9,3,3)"
          hostRef={(node) => (chartRefs.current.kdj = node)}
          metrics={latest ? [["K", formatNullable(latest.kdjK)], ["D", formatNullable(latest.kdjD)], ["J", formatNullable(latest.kdjJ)]] : []}
        />
      </div>
    </section>
  );
}

function buildMinuteChartOptions(height: number) {
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
    crosshair: { mode: CrosshairMode.Normal },
    rightPriceScale: {
      borderColor: chartColors.axis,
      minimumWidth: 56,
      scaleMargins: { bottom: 0.12, top: 0.12 },
    },
    timeScale: {
      borderColor: chartColors.axis,
      rightOffset: 1,
      timeVisible: true,
      secondsVisible: false,
    },
    handleScale: false,
    handleScroll: false,
  };
}

function MinutePanel({
  title,
  hostRef,
  metrics,
  overlay,
}: {
  title: string;
  hostRef: (node: HTMLDivElement | null) => void;
  metrics: Array<[string, string]>;
  overlay?: ReactNode;
}) {
  return (
    <div className="stock-detail-chart-panel" aria-label={title}>
      <div className="panel-header">
        <strong>{title}</strong>
        {metrics.map(([label, value]) => (
          <span className="metric" key={label}>
            {label}:{value}
          </span>
        ))}
      </div>
      <div className="chart-host" ref={hostRef} />
      {overlay}
    </div>
  );
}

function MinuteKlineTooltip({ point, side }: { point: StockMinuteChartPoint; side: "left" | "right" }) {
  const rows: Array<[string, string, string]> = [
    ["时间", formatMinuteTradeTime(point.tradeTime), "secondary"],
    ["开盘", formatNumber(point.open), "flat"],
    ["收盘", formatNumber(point.close), directionClass(resolveMinuteCandleDirection(point.close, point.open))],
    ["最高", formatNumber(point.high), directionClass(resolveMinuteCandleDirection(point.high, point.open))],
    ["最低", formatNumber(point.low), directionClass(resolveMinuteCandleDirection(point.low, point.open))],
    ["成交量", formatMinuteTooltipVolume(point.volume), "secondary"],
    ["成交额", formatMinuteTooltipAmount(point.amount), "secondary"],
  ];
  return (
    <div aria-label="分钟K线数据提示" className={`kline-tooltip ${side}`}>
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

function resolveMinuteStatus(data: StockMinuteChartViewModel): string {
  if (data.dataStatus.status === "DELAYED" || data.indicatorStatus.status === "DELAYED") return "DELAYED";
  if (data.dataStatus.status === "ERROR" || data.indicatorStatus.status === "ERROR") return "ERROR";
  return data.dataStatus.status;
}

function resolveMinuteStatusMessage(data: StockMinuteChartViewModel | null, status: string): string {
  if (!data) return statusMessageFor(status);
  if (data.indicatorStatus.status !== "READY" && data.indicatorStatus.message) return data.indicatorStatus.message;
  if (data.dataStatus.status !== "READY" && data.dataStatus.message) return data.dataStatus.message;
  return statusMessageFor(status);
}

function statusMessageFor(status: string): string {
  if (status === "LOADING") return "正在加载分钟数据";
  if (status === "DELAYED") return "分钟数据尚未覆盖页面期望交易日";
  if (status === "ERROR") return "分钟数据加载失败";
  return "暂无分钟数据";
}

function formatMinuteTradeTime(value: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(value);
  return match ? `${match[1]?.replaceAll("-", "")} ${match[2]}` : value;
}

function resolveMinuteCandleDirection(value: number, open: number): MarketDirection {
  if (!Number.isFinite(value) || !Number.isFinite(open)) return "UNKNOWN";
  if (value > open) return "UP";
  if (value < open) return "DOWN";
  return "FLAT";
}

function formatMinuteTooltipVolume(value: number): string {
  if (!Number.isFinite(value)) return "--";
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿股`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(2)}万股`;
  return `${Math.round(value)}股`;
}

function formatMinuteTooltipAmount(value: number): string {
  if (!Number.isFinite(value)) return "--";
  if (value >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿元`;
  if (value >= 10_000) return `${(value / 10_000).toFixed(2)}万元`;
  return `${value.toFixed(2)}元`;
}

function formatNumber(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : "--";
}

function formatNullable(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "--" : value.toFixed(2);
}
