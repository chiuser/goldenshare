import { formatSignedPercent } from "../../../../shared/lib/formatters";
import type { MultiTrendPoint } from "../../../../shared/model/market";
import type { MarketOverview, MetricItem } from "../../api/marketOverviewTypes";
import type { MarketTurnoverResponse } from "./marketTurnoverApi";

const THOUSAND_YUAN_PER_YI = 100000;

export interface MarketTurnoverViewModel {
  metrics: MetricItem[];
  chartsByRange: Record<"1m" | "3m", { intraday: MultiTrendPoint[]; history: MultiTrendPoint[] }>;
  statusLabel: string;
  statusTone: "ready" | "delayed";
  source: "mock" | "real";
}

function toYiFromThousandYuan(value: number | null | undefined): number | null {
  if (value === null || typeof value === "undefined") return null;
  return value / THOUSAND_YUAN_PER_YI;
}

function formatYi(value: number | null | undefined): string {
  const yi = toYiFromThousandYuan(value);
  if (yi === null) return "--";
  return `${Math.round(yi)}亿`;
}

function formatSignedYi(value: number | null | undefined): string {
  const yi = toYiFromThousandYuan(value);
  if (yi === null) return "--";
  const rounded = Math.round(yi);
  const prefix = rounded > 0 ? "+" : "";
  return `${prefix}${rounded}亿`;
}

function formatAmountDeltaPct(value: number | null | undefined): string {
  if (value === null || typeof value === "undefined") return "--";
  return formatSignedPercent(value);
}

function mapHistoryPoints(points: Array<{ tradeDate: string; amount?: number | null }>): MultiTrendPoint[] {
  return points.map((point) => ({
    label: point.tradeDate.slice(5),
    amount: toYiFromThousandYuan(point.amount) ?? 0,
  }));
}

function mapIntradayPoints(points: Array<{ time: string; cumAmount?: number | null }>): MultiTrendPoint[] {
  return points.map((point) => ({
    label: point.time,
    amount: toYiFromThousandYuan(point.cumAmount) ?? 0,
  }));
}

export function buildTurnoverViewModelFromMock(overview: MarketOverview): MarketTurnoverViewModel {
  return {
    metrics: overview.turnoverMetrics,
    chartsByRange: {
      "1m": {
        intraday: overview.charts.turnoverIntraday,
        history: overview.charts.turnoverHistory["1m"],
      },
      "3m": {
        intraday: overview.charts.turnoverIntraday,
        history: overview.charts.turnoverHistory["3m"],
      },
    },
    statusLabel: "事实聚合已就绪",
    statusTone: "ready",
    source: "mock",
  };
}

export function buildTurnoverViewModelFromApi(payload: MarketTurnoverResponse): MarketTurnoverViewModel {
  const metrics = payload.turnover.metrics;
  return {
    metrics: [
      { label: "今日成交总额", value: formatYi(metrics.todayAmount), tone: "up", sub: "截至 15:00" },
      {
        label: "较上一交易日",
        value: formatSignedYi(metrics.amountDelta),
        tone:
          typeof metrics.amountDelta === "number"
            ? metrics.amountDelta > 0
              ? "up"
              : metrics.amountDelta < 0
                ? "down"
                : "flat"
            : "flat",
        sub: formatAmountDeltaPct(metrics.amountDeltaPct),
      },
      {
        label: "上一交易日成交",
        value: formatYi(metrics.prevAmount),
        tone: "flat",
        sub: payload.tradingDay.prevTradeDate ?? "--",
      },
      {
        label: "5日均值",
        value: formatYi(metrics.avg5dAmount),
        tone: "flat",
        sub: `20日均值 ${formatYi(metrics.avg20dAmount)}`,
      },
    ],
    chartsByRange: {
      "1m": {
        intraday: mapIntradayPoints(payload.turnover.intradayCumulative),
        history: mapHistoryPoints(payload.turnover.historyByRange.oneMonth),
      },
      "3m": {
        intraday: mapIntradayPoints(payload.turnover.intradayCumulative),
        history: mapHistoryPoints(payload.turnover.historyByRange.threeMonth),
      },
    },
    statusLabel: payload.pageStatus.displayText,
    statusTone: payload.pageStatus.status === "READY" ? "ready" : "delayed",
    source: "real",
  };
}
