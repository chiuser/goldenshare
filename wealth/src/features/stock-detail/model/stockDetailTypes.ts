import type { MarketDirection } from "../../../shared/model/market";
import type { TopMarketTicker } from "../../../shared/ui/top-market-bar/topMarketBarTypes";

export type StockPeriodKey =
  | "timeShare"
  | "day"
  | "week"
  | "month"
  | "m120"
  | "m90"
  | "m60"
  | "m30"
  | "m15"
  | "m5"
  | "m1";

export type StockMainOverlay = "MA" | "BOLL";

export interface StockPeriodOption {
  key: StockPeriodKey;
  label: string;
  supported?: boolean;
}

export interface StockIndicatorTab {
  key: string;
  label: string;
  active: boolean;
  supported: boolean;
  overlay?: StockMainOverlay;
}

export interface StockIdentity {
  tsCode: string;
  name: string;
  market: string;
  sector: string;
  tags: string[];
}

export interface StockQuoteSnapshot {
  price: number;
  change: number;
  changePct: number;
  direction: MarketDirection;
  open: number;
  prevClose: number;
  high: number;
  low: number;
  turnoverRate: number;
  volumeRatio: number;
  volumeText: string;
  amountText: string;
}

export interface StockCandlePoint {
  time: string;
  fullDate: string;
  open: number;
  high: number;
  low: number;
  close: number;
  preClose: number;
  changePct: number;
  amplitude: number;
  volume: number;
  amount: number;
  turnoverRate: number;
  volumeRatio: number;
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma30: number | null;
  ma60: number | null;
  ma90: number | null;
  ma250: number | null;
  bollUpper: number;
  bollMiddle: number;
  bollLower: number;
  macd: number;
  dif: number;
  dea: number;
  k: number;
  d: number;
  j: number;
}

export interface StockChartSeries {
  candles: StockCandlePoint[];
}

export interface RelatedSectorRow {
  name: string;
  pct: number;
  count: number;
  type: string;
  direction: MarketDirection;
}

export interface StockMoneyFlowRow {
  label: string;
  value: number;
  direction: MarketDirection;
  ratio: number;
}

export interface StockDetailViewModel {
  topMarketTickers: TopMarketTicker[];
  stock: StockIdentity;
  quote: StockQuoteSnapshot;
  periods: StockPeriodOption[];
  activePeriod: StockPeriodKey;
  chart: StockChartSeries;
  indicatorTabs: StockIndicatorTab[];
  rightRail: {
    sectors: RelatedSectorRow[];
    moneyFlow: StockMoneyFlowRow[];
    productBoundaryNotes: string[];
  };
}
