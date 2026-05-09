import { formatSignedPercent } from "../../../../shared/lib/formatters";
import type { MultiTrendPoint } from "../../../../shared/model/market";
import type { MarketOverview, MetricItem } from "../../api/marketOverviewTypes";
import type { MarketStyleResponse } from "./marketStyleApi";

export interface MarketStyleViewModel {
  metrics: MetricItem[];
  chartsByRange: Record<"1m" | "3m", MultiTrendPoint[]>;
  statusLabel: string;
  statusTone: "ready" | "delayed";
  source: "mock" | "real";
}

function mapTone(direction: string): MetricItem["tone"] {
  if (direction === "UP") return "up";
  if (direction === "DOWN") return "down";
  return "flat";
}

function formatStylePct(value: number | null | undefined): string {
  if (value === null || typeof value === "undefined") return "--";
  return formatSignedPercent(value);
}

function mapHistoryPoints(
  points: Array<{ tradeDate: string; largePct?: number | null; smallPct?: number | null; medianPct?: number | null }>,
): MultiTrendPoint[] {
  return points.map((point) => ({
    label: point.tradeDate.slice(5),
    large: point.largePct ?? 0,
    small: point.smallPct ?? 0,
    median: point.medianPct ?? 0,
  }));
}

export function buildStyleViewModelFromMock(overview: MarketOverview): MarketStyleViewModel {
  return {
    metrics: overview.styleMetrics,
    chartsByRange: {
      "1m": overview.charts.style["1m"],
      "3m": overview.charts.style["3m"],
    },
    statusLabel: "事实聚合已就绪",
    statusTone: "ready",
    source: "mock",
  };
}

export function buildStyleViewModelFromApi(payload: MarketStyleResponse): MarketStyleViewModel {
  return {
    metrics: payload.style.cards.map((card) => ({
      label: card.label,
      value: formatStylePct(card.valuePct ?? null),
      tone: mapTone(card.direction),
      sub: card.sourceText,
    })),
    chartsByRange: {
      "1m": mapHistoryPoints(payload.style.historyByRange.oneMonth),
      "3m": mapHistoryPoints(payload.style.historyByRange.threeMonth),
    },
    statusLabel: payload.pageStatus.displayText,
    statusTone: payload.pageStatus.status === "READY" ? "ready" : "delayed",
    source: "real",
  };
}
