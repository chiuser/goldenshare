import { formatSignedAmountYi } from "../../../../shared/lib/formatters";
import type { MultiTrendPoint } from "../../../../shared/model/market";
import type { MarketOverview, MetricItem, MoneyFlowOrderSizeItem } from "../../api/marketOverviewTypes";
import type { MarketMoneyFlowResponse } from "./marketMoneyFlowApi";

const YUAN_PER_YI = 100000000;

export interface MarketMoneyFlowViewModel {
  metrics: MetricItem[];
  orderSizeItems: MoneyFlowOrderSizeItem[];
  chartsByRange: Record<"1m" | "3m", MultiTrendPoint[]>;
  statusLabel: string;
  statusTone: "ready" | "delayed";
  source: "mock" | "real";
}

function toYiFromYuan(value: number | null | undefined): number | null {
  if (value === null || typeof value === "undefined") return null;
  return value / YUAN_PER_YI;
}

function formatSignedYiFromYuan(value: number | null | undefined): string {
  const yi = toYiFromYuan(value);
  if (yi === null) return "--";
  return formatSignedAmountYi(yi);
}

function toneByAmount(value: number | null | undefined): MetricItem["tone"] {
  if (typeof value !== "number") return "flat";
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}

function directionByAmount(value: number | null | undefined): MoneyFlowOrderSizeItem["direction"] {
  if (typeof value !== "number") return "flat";
  if (value > 0) return "inflow";
  if (value < 0) return "outflow";
  return "flat";
}

function flowSubText(value: number | null | undefined): string {
  if (typeof value !== "number") return "数据源：moneyflow_mkt_dc";
  if (value > 0) return "净流入；数据源：moneyflow_mkt_dc";
  if (value < 0) return "净流出；数据源：moneyflow_mkt_dc";
  return "资金基本平衡；数据源：moneyflow_mkt_dc";
}

function mapHistoryPoints(points: Array<{ tradeDate: string; netAmount?: number | null }>): MultiTrendPoint[] {
  return points.map((point) => ({
    label: point.tradeDate.slice(5),
    net: toYiFromYuan(point.netAmount) ?? 0,
  }));
}

function mapOrderSizeItem(
  orderSize: MoneyFlowOrderSizeItem["orderSize"],
  orderSizeName: string,
  item: { amount?: number | null; rate?: number | null },
): MoneyFlowOrderSizeItem {
  const netAmount = toYiFromYuan(item.amount) ?? 0;
  return {
    orderSize,
    orderSizeName,
    netAmount,
    netAmountRate: item.rate ?? 0,
    absAmount: Math.abs(netAmount),
    direction: directionByAmount(item.amount),
  };
}

export function buildMoneyFlowViewModelFromMock(overview: MarketOverview): MarketMoneyFlowViewModel {
  return {
    metrics: overview.moneyFlowMetrics,
    orderSizeItems: overview.moneyFlowOrderSizeStructure.items,
    chartsByRange: {
      "1m": overview.charts.moneyFlow["1m"],
      "3m": overview.charts.moneyFlow["3m"],
    },
    statusLabel: "事实聚合已就绪",
    statusTone: "ready",
    source: "mock",
  };
}

export function buildMoneyFlowViewModelFromApi(payload: MarketMoneyFlowResponse): MarketMoneyFlowViewModel {
  const metrics = payload.moneyFlow.metrics;
  return {
    metrics: [
      {
        label: "今日大盘资金净流入",
        value: formatSignedYiFromYuan(metrics.todayNetAmount),
        tone: toneByAmount(metrics.todayNetAmount),
        sub: flowSubText(metrics.todayNetAmount),
      },
      {
        label: "上一交易日大盘资金净流入",
        value: formatSignedYiFromYuan(metrics.prevNetAmount),
        tone: toneByAmount(metrics.prevNetAmount),
        sub: payload.tradingDay.prevTradeDate ?? "--",
      },
    ],
    orderSizeItems: [
      mapOrderSizeItem("superLarge", "超大单", payload.moneyFlow.byOrderSize.elg),
      mapOrderSizeItem("large", "大单", payload.moneyFlow.byOrderSize.lg),
      mapOrderSizeItem("medium", "中单", payload.moneyFlow.byOrderSize.md),
      mapOrderSizeItem("small", "小单", payload.moneyFlow.byOrderSize.sm),
    ],
    chartsByRange: {
      "1m": mapHistoryPoints(payload.moneyFlow.historyByRange.oneMonth),
      "3m": mapHistoryPoints(payload.moneyFlow.historyByRange.threeMonth),
    },
    statusLabel: payload.pageStatus.displayText,
    statusTone: payload.pageStatus.status === "READY" ? "ready" : "delayed",
    source: "real",
  };
}
