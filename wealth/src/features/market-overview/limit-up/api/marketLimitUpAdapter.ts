import type { MultiTrendPoint } from "../../../../shared/model/market";
import type { MetricItem, MarketOverview } from "../../api/marketOverviewTypes";
import type { MarketLimitUpResponse } from "./marketLimitUpApi";

export interface LimitSectorItemView {
  sectorCode: string;
  sectorName: string;
  sectorType: "CONCEPT" | "INDUSTRY" | "REGION" | "OTHER";
  limitUpCount: number;
  ratio: number;
}

export interface LimitLeaderPerformanceItemView {
  stockCode: string;
  stockName: string;
  latestPrice: number | null;
  changePct: number | null;
  rank: number;
  streakLabel: string;
  recentLimitText: string;
  firstLimitTime: string;
  openTimes: number;
  sealedAmountDisplayText: string;
}

export interface LimitSectorLeaderStructureView {
  tradeDate: string;
  selectedSectorCode: string;
  selectedStockCode: string;
  sectors: LimitSectorItemView[];
  leaderStocks: Record<string, LimitLeaderPerformanceItemView[]>;
}

export interface MarketLimitUpViewModel {
  statusLabel: string;
  statusTone: "ready" | "delayed";
  metrics: MetricItem[];
  historyByRange: Record<"1m" | "3m", MultiTrendPoint[]>;
  structures: {
    today: LimitSectorLeaderStructureView;
    yesterday: LimitSectorLeaderStructureView;
  };
  source: "mock" | "real";
}

function mapDirectionTone(direction: string): MetricItem["tone"] {
  if (direction === "UP") return "up";
  if (direction === "DOWN") return "down";
  return "flat";
}

function formatCardValue(value: string | number | null, unit?: string | null): string {
  if (value === null || typeof value === "undefined") return "--";
  if (typeof value === "string") return value;
  if (unit === "%") return `${value.toFixed(1)}%`;
  if (unit) return `${value}${unit}`;
  return String(value);
}

function formatTradeDateLabel(tradeDate: string): string {
  if (!tradeDate) return "--";
  const [year, month, day] = tradeDate.split("-");
  if (!year || !month || !day) return tradeDate;
  return `${month}-${day}`;
}

function toHistoryPoints(
  points: Array<{ tradeDate: string; limitUpCount: number; limitDownCount: number }>,
): MultiTrendPoint[] {
  return points.map((point) => ({
    label: formatTradeDateLabel(point.tradeDate),
    up: point.limitUpCount,
    down: point.limitDownCount,
  }));
}

function toStructureView(block: MarketLimitUpResponse["limitUp"]["todayStructure"]): LimitSectorLeaderStructureView {
  const maxLimitUpCount = Math.max(1, ...block.sectors.map((item) => item.limitUpCount));
  const sectors: LimitSectorItemView[] = block.sectors.map((sector) => ({
    sectorCode: sector.sectorCode,
    sectorName: sector.sectorName,
    sectorType: sector.sectorType,
    limitUpCount: sector.limitUpCount,
    ratio: Math.max(0, Math.round((sector.limitUpCount / maxLimitUpCount) * 100)),
  }));
  const leaderStocks: Record<string, LimitLeaderPerformanceItemView[]> = {};
  Object.entries(block.leaderStocks).forEach(([sectorCode, items]) => {
    leaderStocks[sectorCode] = items.map((item) => ({
      stockCode: item.stockCode,
      stockName: item.stockName?.trim() || item.stockCode,
      latestPrice: typeof item.latestPrice === "number" ? item.latestPrice : null,
      changePct: typeof item.changePct === "number" ? item.changePct : null,
      rank: item.rank,
      streakLabel: item.streakLabel,
      recentLimitText: item.recentLimitText,
      firstLimitTime: item.firstLimitTime,
      openTimes: item.openTimes,
      sealedAmountDisplayText: item.sealedAmountDisplayText,
    }));
  });
  const fallbackSectorCode = sectors[0]?.sectorCode ?? "";
  const selectedSectorCode = block.selectedSectorCode || fallbackSectorCode;
  const selectedStockCode = block.selectedStockCode || leaderStocks[selectedSectorCode]?.[0]?.stockCode || "";
  return {
    tradeDate: block.tradeDate,
    selectedSectorCode,
    selectedStockCode,
    sectors,
    leaderStocks,
  };
}

export function buildLimitUpViewModelFromMock(overview: MarketOverview): MarketLimitUpViewModel {
  const yesterdayTradeDate = buildPreviousDay(overview.tradeDate);
  return {
    statusLabel: "事实聚合已就绪",
    statusTone: "ready",
    metrics: overview.limitMetrics,
    historyByRange: {
      "1m": overview.charts.limitHistory["1m"],
      "3m": overview.charts.limitHistory["3m"],
    },
    structures: {
      today: {
        tradeDate: overview.tradeDate,
        selectedSectorCode: overview.limitStructures.today.selectedSectorCode,
        selectedStockCode: overview.limitStructures.today.selectedStockCode,
        sectors: overview.limitStructures.today.sectors,
        leaderStocks: overview.limitStructures.today.leaderStocks,
      },
      yesterday: {
        tradeDate: yesterdayTradeDate,
        selectedSectorCode: overview.limitStructures.yesterday.selectedSectorCode,
        selectedStockCode: overview.limitStructures.yesterday.selectedStockCode,
        sectors: overview.limitStructures.yesterday.sectors,
        leaderStocks: overview.limitStructures.yesterday.leaderStocks,
      },
    },
    source: "mock",
  };
}

function buildPreviousDay(tradeDate: string): string {
  const date = new Date(`${tradeDate}T00:00:00+08:00`);
  if (Number.isNaN(date.getTime())) return tradeDate;
  date.setDate(date.getDate() - 1);
  return `${date.getFullYear()}-${`${date.getMonth() + 1}`.padStart(2, "0")}-${`${date.getDate()}`.padStart(2, "0")}`;
}

export function buildLimitUpViewModelFromApi(payload: MarketLimitUpResponse): MarketLimitUpViewModel {
  return {
    statusLabel: payload.pageStatus.displayText,
    statusTone: payload.pageStatus.status === "READY" ? "ready" : "delayed",
    metrics: payload.limitUp.summaryCards.map((card) => ({
      label: card.label,
      value: formatCardValue(card.value, card.unit ?? null),
      tone: mapDirectionTone(card.direction),
      sub: card.subText ?? "",
    })),
    historyByRange: {
      "1m": toHistoryPoints(payload.limitUp.historyPoints.oneMonth),
      "3m": toHistoryPoints(payload.limitUp.historyPoints.threeMonth),
    },
    structures: {
      today: toStructureView(payload.limitUp.todayStructure),
      yesterday: toStructureView(payload.limitUp.yesterdayStructure),
    },
    source: "real",
  };
}
