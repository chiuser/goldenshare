import type { MultiTrendPoint } from "../../../../shared/model/market";
import type { MarketOverview, MetricItem } from "../../api/marketOverviewTypes";
import type { BreadthDistributionBuckets, BreadthHistoryPoint, MarketBreadthResponse } from "./marketBreadthApi";

export interface MarketBreadthFactPoint {
  tradeDate: string;
  upCount: number;
  downCount: number;
  flatCount: number;
  totalCount: number;
  redRate: number;
  distributionBuckets: BreadthDistributionBuckets;
}

export interface MarketBreadthMetricsFact {
  upCount: number;
  downCount: number;
  flatCount: number;
  totalCount: number;
  redRate: number;
  distributionBuckets: BreadthDistributionBuckets;
}

export interface MarketBreadthViewModel {
  metrics: MetricItem[];
  chartsByRange: Record<"1m" | "3m", MultiTrendPoint[]>;
  metricsFact?: MarketBreadthMetricsFact;
  factsByRange?: Record<"1m" | "3m", MarketBreadthFactPoint[]>;
  statusLabel: string;
  statusTone: "ready" | "delayed";
  source: "mock" | "real";
}

function buildMetrics(
  upCount: number,
  downCount: number,
  flatCount: number,
  totalCount: number,
  redRate: number,
): MetricItem[] {
  const greenRate = totalCount > 0 ? (downCount / totalCount) * 100 : 0;
  const flatRate = totalCount > 0 ? (flatCount / totalCount) * 100 : 0;
  return [
    { label: "上涨家数", value: String(upCount), tone: "up", sub: `红盘率 ${redRate.toFixed(1)}%` },
    { label: "下跌家数", value: String(downCount), tone: "down", sub: `绿盘率 ${greenRate.toFixed(1)}%` },
    { label: "平盘家数", value: String(flatCount), tone: "flat", sub: `平盘率 ${flatRate.toFixed(1)}%` },
  ];
}

function mapHistoryPoints(points: BreadthHistoryPoint[]): MultiTrendPoint[] {
  return points.map((point) => ({
    label: point.tradeDate.slice(5),
    up: point.upCount,
    down: point.downCount,
  }));
}

function mapFactPoints(points: BreadthHistoryPoint[]): MarketBreadthFactPoint[] {
  return points.map((point) => ({
    tradeDate: point.tradeDate,
    upCount: point.upCount,
    downCount: point.downCount,
    flatCount: point.flatCount,
    totalCount: point.totalCount,
    redRate: point.redRate,
    distributionBuckets: point.distributionBuckets,
  }));
}

export function buildBreadthViewModelFromMock(overview: MarketOverview): MarketBreadthViewModel {
  return {
    metrics: overview.breadthMetrics,
    chartsByRange: {
      "1m": overview.charts.breadth["1m"],
      "3m": overview.charts.breadth["3m"],
    },
    statusLabel: "事实聚合已就绪",
    statusTone: "ready",
    source: "mock",
  };
}

export function buildBreadthViewModelFromApi(payload: MarketBreadthResponse): MarketBreadthViewModel {
  return {
    metrics: buildMetrics(
      payload.breadth.metrics.upCount,
      payload.breadth.metrics.downCount,
      payload.breadth.metrics.flatCount,
      payload.breadth.metrics.totalCount,
      payload.breadth.metrics.redRate,
    ),
    chartsByRange: {
      "1m": mapHistoryPoints(payload.breadth.historyByRange["1m"]),
      "3m": mapHistoryPoints(payload.breadth.historyByRange["3m"]),
    },
    metricsFact: payload.breadth.metrics,
    factsByRange: {
      "1m": mapFactPoints(payload.breadth.historyByRange["1m"]),
      "3m": mapFactPoints(payload.breadth.historyByRange["3m"]),
    },
    statusLabel: payload.pageStatus.displayText,
    statusTone: payload.pageStatus.status === "READY" ? "ready" : "delayed",
    source: "real",
  };
}
