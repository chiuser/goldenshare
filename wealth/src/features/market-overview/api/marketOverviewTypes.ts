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

export interface LimitStructureRow {
  name: string;
  count: number;
  ratio: number;
  kind: "up" | "down" | "fail";
}

export interface LimitStructure {
  up: LimitStructureRow[];
  downBroken: LimitStructureRow[];
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
    today: LimitStructure;
    yesterday: LimitStructure;
  };
  ladder: LadderLevel[];
  sectors: {
    columns: SectorColumn[];
    heatmap: HeatCell[];
  };
}
