import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";

import type { StockMinuteChartPoint, StockMinuteChartViewModel } from "../api/stockMinuteViewModelAdapter";

interface StockMinuteChartWorkspaceProps {
  data: StockMinuteChartViewModel | null;
  loadState: "idle" | "loading" | "ready" | "error";
  errorMessage?: string;
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
};

const minuteChartHeight = 112;

export function StockMinuteChartWorkspace({ data, loadState, errorMessage }: StockMinuteChartWorkspaceProps) {
  const chartRefs = useRef({
    kline: null as HTMLDivElement | null,
    macd: null as HTMLDivElement | null,
    volume: null as HTMLDivElement | null,
    kdj: null as HTMLDivElement | null,
  });

  useEffect(() => {
    if (!data || data.points.length === 0) return;
    if (Object.values(chartRefs.current).some((host) => host === null)) return;

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
    addNullableLine(kdjChart, chartColors.brand, "kdjK");
    addNullableLine(kdjChart, chartColors.blue, "kdjD");
    addNullableLine(kdjChart, chartColors.purple, "kdjJ");

    charts.forEach((chart) => chart.timeScale().fitContent());
    return () => charts.forEach((chart) => chart.remove());
  }, [data]);

  const latest = data?.points.at(-1);
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
      <div className="stock-detail-charts-area">
        <div className="stock-minute-chart-status" role="status">
          <span>{statusMessage}</span>
          <span>freq={data.freq}</span>
        </div>
        <MinutePanel title="分钟K线" hostRef={(node) => (chartRefs.current.kline = node)} metrics={latest ? [["收盘", formatNumber(latest.close)]] : []} />
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
}: {
  title: string;
  hostRef: (node: HTMLDivElement | null) => void;
  metrics: Array<[string, string]>;
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

function formatNumber(value: number): string {
  return Number.isFinite(value) ? value.toFixed(2) : "--";
}

function formatNullable(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "--" : value.toFixed(2);
}
