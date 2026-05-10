import type { DataStatus, MarketDirection, MultiTrendPoint } from "../../../shared/model/market";

export interface WealthApiResponse<T> {
  code: number;
  message: string;
  data: T;
  traceId: string;
  serverTime: string;
}

export interface MarketOverviewParams {
  market?: "CN_A";
  tradeDate?: string;
  dataMode?: "latest" | "eod" | "replay";
}

export interface QuoteItem {
  code: string;
  name: string;
  point: number;
  change: number;
  pct: number;
  direction: MarketDirection;
}

export interface FactItem {
  label: string;
  value: string;
  valueTone?: "up" | "down" | "flat";
  sub: string;
}

export interface MetricItem {
  label: string;
  value: string;
  tone?: "up" | "down" | "flat";
  sub: string;
}

export interface LeaderboardRow {
  name: string;
  code: string;
  latestPrice: number;
  changePct: number;
  turnoverRate: number;
  volumeRatio: number;
  volume: string;
  amount: string;
}

export interface LeaderboardTab {
  key: string;
  label: string;
  rows: LeaderboardRow[];
}

export interface MoneyFlowOrderSizeItem {
  orderSize: "superLarge" | "large" | "medium" | "small";
  orderSizeName: string;
  netAmount: number;
  netAmountRate: number;
  absAmount: number;
  direction: "inflow" | "outflow" | "flat";
}

export interface MoneyFlowOrderSizeStructure {
  netAmount: number;
  netAmountRate: number;
  items: MoneyFlowOrderSizeItem[];
}

export interface LimitSectorItem {
  sectorCode: string;
  sectorName: string;
  sectorType: "CONCEPT" | "INDUSTRY" | "REGION" | "OTHER";
  limitUpCount: number;
  ratio: number;
}

export interface LimitLeaderPerformanceItem {
  stockCode: string;
  stockName: string;
  latestPrice: number;
  changePct: number;
  rank: number;
  streakLabel: string;
  recentLimitText: string;
  firstLimitTime: string;
  openTimes: number;
  sealedAmountDisplayText: string;
}

export interface LimitSectorLeaderStructure {
  selectedSectorCode: string;
  selectedStockCode: string;
  sectors: LimitSectorItem[];
  leaderStocks: Record<string, LimitLeaderPerformanceItem[]>;
}

export interface LadderLevel {
  level: string;
  count: number;
  stocks: Array<{
    name: string;
    code: string;
    theme: string;
    price: string;
    changePct: string;
    openTimes: string;
  }>;
}

export interface SectorRankRow {
  name: string;
  text: string;
  value: number;
}

export interface SectorColumn {
  key: string;
  title: string;
  tone: "up" | "down";
  valueLabel: string;
  rows: SectorRankRow[];
}

export interface HeatCell {
  name: string;
  pct: number;
}

export interface MarketOverview {
  tradeDate: string;
  updateTime: string;
  statusText: string;
  dataStatus: DataStatus;
  dataDelayText: string;
  tickers: QuoteItem[];
  summaryFacts: FactItem[];
  summaryText: string;
  indices: QuoteItem[];
  breadthMetrics: MetricItem[];
  styleMetrics: MetricItem[];
  turnoverMetrics: MetricItem[];
  moneyFlowMetrics: MetricItem[];
  moneyFlowOrderSizeStructure: MoneyFlowOrderSizeStructure;
  limitMetrics: MetricItem[];
  charts: {
    breadth: Record<string, MultiTrendPoint[]>;
    style: Record<string, MultiTrendPoint[]>;
    turnoverIntraday: MultiTrendPoint[];
    turnoverHistory: Record<string, MultiTrendPoint[]>;
    moneyFlow: Record<string, MultiTrendPoint[]>;
    limitHistory: Record<string, MultiTrendPoint[]>;
  };
  leaderboards: LeaderboardTab[];
  limitStructures: {
    today: LimitSectorLeaderStructure;
    yesterday: LimitSectorLeaderStructure;
  };
  ladder: LadderLevel[];
  sectors: {
    columns: SectorColumn[];
    heatmap: HeatCell[];
  };
}
