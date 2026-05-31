import type { MarketDirection } from "../../../shared/model/market";

export interface StockDetailPageContextDto {
  market: "CN_A";
  tradeDate: string;
  prevTradeDate?: string | null;
  isTradingDay: boolean;
  sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
  timezone: "Asia/Shanghai";
  generatedAt: string;
  source: "explicit" | "default";
}

export interface StockDetailStockIdentityDto {
  tsCode: string;
  symbol?: string | null;
  name: string;
  market?: string | null;
  exchange?: string | null;
  industry?: string | null;
  area?: string | null;
  listStatus?: string | null;
  tags: string[];
}

export interface StockQuoteSnapshotDto {
  tradeDate: string;
  price?: number | null;
  change?: number | null;
  changePct?: number | null;
  direction: MarketDirection | "UNKNOWN";
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  preClose?: number | null;
  turnoverRate?: number | null;
  volumeRatio?: number | null;
  vol?: number | null;
  amount?: number | null;
}

export interface StockChartDefaultsDto {
  defaultPeriod: "day";
  defaultAdjustment: "forward";
  sourceAdjustment: "qfq";
  availablePeriods: ["day"];
  availableAdjustments: ["forward"];
  availableMainOverlays: Array<"MA" | "BOLL">;
  availableIndicatorTabs: Array<"VOL" | "amount" | "MA" | "MACD" | "KDJ" | "BOLL">;
}

export interface StockDetailCapabilitiesDto {
  supportsRealtime: boolean;
  supportsMinute: boolean;
  supportsWeeklyMonthly: boolean;
  supportsUserActions: boolean;
  unsupportedActions: string[];
}

export interface StockDetailDataStatusDto {
  status: "READY" | "DELAYED" | "EMPTY" | "ERROR";
  expectedTradeDate: string;
  observedTradeDate?: string | null;
  note?: string | null;
}

export interface StockDetailPageInitResponseDto {
  pageContext: StockDetailPageContextDto;
  stock: StockDetailStockIdentityDto;
  quote?: StockQuoteSnapshotDto | null;
  chartDefaults: StockChartDefaultsDto;
  capabilities: StockDetailCapabilitiesDto;
  dataStatus: StockDetailDataStatusDto;
  debugInfo?: unknown;
}

export interface StockKlineBarDto {
  tradeDate: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  preClose?: number | null;
  change?: number | null;
  changePct?: number | null;
  vol?: number | null;
  amount?: number | null;
  turnoverRate?: number | null;
  volumeRatio?: number | null;
  factors: {
    ma: {
      ma5?: number | null;
      ma10?: number | null;
      ma20?: number | null;
      ma30?: number | null;
      ma60?: number | null;
      ma90?: number | null;
      ma250?: number | null;
    };
    boll: {
      upper?: number | null;
      middle?: number | null;
      lower?: number | null;
    };
    macd: {
      dif?: number | null;
      dea?: number | null;
      macd?: number | null;
    };
    kdj: {
      k?: number | null;
      d?: number | null;
      j?: number | null;
    };
  };
}

export interface StockDetailKlineResponseDto {
  pageContext: StockDetailPageContextDto;
  stockRef: {
    tsCode: string;
    name?: string | null;
  };
  period: "day";
  adjustment: "forward";
  sourceAdjustment: "qfq";
  bars: StockKlineBarDto[];
  meta: {
    count: number;
    limit: number;
    startDate?: string | null;
    endDate?: string | null;
  };
  dataStatus: StockDetailDataStatusDto;
  debugInfo?: unknown;
}
