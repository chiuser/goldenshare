import type { MultiTrendPoint } from "../../../../shared/model/market";
import type { MarketOverview, MetricItem } from "../../api/marketOverviewTypes";
import type { MarketBreadthResponse } from "./marketBreadthApi";

export interface MarketBreadthViewModel {
  metrics: MetricItem[];
  chartsByRange: Record<"1m" | "3m", MultiTrendPoint[]>;
  statusLabel: string;
  statusTone: "ready" | "delayed";
  source: "mock" | "real";
}

function buildMetrics(
  upCount: number,
  downCount: number,
  flatCount: number,
  redRate: number,
): MetricItem[] {
  const total = upCount + downCount + flatCount;
  const greenRate = total > 0 ? (downCount / total) * 100 : 0;
  const flatRate = total > 0 ? (flatCount / total) * 100 : 0;
  return [
    { label: "上涨家数", value: String(upCount), tone: "up", sub: `红盘率 ${redRate.toFixed(1)}%` },
    { label: "下跌家数", value: String(downCount), tone: "down", sub: `绿盘率 ${greenRate.toFixed(1)}%` },
    { label: "平盘家数", value: String(flatCount), tone: "flat", sub: `平盘率 ${flatRate.toFixed(1)}%` },
  ];
}

function mapHistoryPoints(points: Array<{ tradeDate: string; upCount: number; downCount: number }>): MultiTrendPoint[] {
  return points.map((point) => ({
    label: point.tradeDate.slice(5),
    up: point.upCount,
    down: point.downCount,
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
      payload.breadth.metrics.redRate,
    ),
    chartsByRange: {
      "1m": mapHistoryPoints(payload.breadth.historyByRange["1m"]),
      "3m": mapHistoryPoints(payload.breadth.historyByRange["3m"]),
    },
    statusLabel: payload.pageStatus.displayText,
    statusTone: payload.pageStatus.status === "READY" ? "ready" : "delayed",
    source: "real",
  };
}
