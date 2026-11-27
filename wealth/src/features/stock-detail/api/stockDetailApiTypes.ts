import type { MarketDirection } from "../../../shared/model/market";
import type { NineTurnMarkerDto, NineTurnPeriod } from "../../nine-turn/api/nineTurnApiTypes";

export type StockMinuteFrequency = 1 | 5 | 15 | 30 | 60 | 90 | 120;
export type StockKlinePeriod = "day" | "week" | "month";

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
  volDisplay: string | null;
  amount?: number | null;
}

export interface StockChartDefaultsDto {
  defaultPeriod: "day";
  defaultAdjustment: "forward";
  sourceAdjustment: "qfq";
  availablePeriods: StockKlinePeriod[];
  availableAdjustments: ["forward"];
  availableMainOverlays: Array<"MA" | "BOLL" | "TREND_CHANNEL">;
  availableIndicatorTabs: Array<"VOL" | "amount" | "MA" | "MACD" | "KDJ" | "BOLL">;
}

export interface StockDetailCapabilitiesDto {
  supportsRealtime: boolean;
  supportsMinute: boolean;
  minuteFrequencies?: StockMinuteFrequency[];
  nineTurnPeriods: Array<NineTurnPeriod | "week" | "month">;
  supportsNineTurn: boolean;
  supportsTrendChannel: boolean;
  supportsWeeklyMonthly: boolean;
  userActions: { watchlist: boolean; alert: boolean; tradePlan: boolean; diagnosis: boolean };
}

export interface StockDetailDataStatusDto {
  status: "READY" | "DELAYED" | "EMPTY" | "ERROR";
  expectedTradeDate: string;
  observedTradeDate?: string | null;
  note?: string | null;
}

interface StockDetailPageInitFields {
  pageContext: StockDetailPageContextDto;
  stock: StockDetailStockIdentityDto;
  chartDefaults: StockChartDefaultsDto;
  capabilities: StockDetailCapabilitiesDto;
  debugInfo?: unknown;
}

export interface StockDetailProdPageInitResponseDto extends StockDetailPageInitFields {
  quote: StockQuoteSnapshotDto | null;
  dataStatus: StockDetailDataStatusDto;
}

export type StockDetailPageInitResponseDto = StockDetailProdPageInitResponseDto
  | (StockDetailPageInitFields & { quote?: never; dataStatus?: never });

export interface StockKlineBarDto {
  tradeDate: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  preClose?: number | null;
  change?: number | null;
  changePct?: number | null;
  amplitude?: number | null;
  vol?: number | null;
  volDisplay: string | null;
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

export interface StockTrendChannelFactorsDto {
  shortUpper: number;
  shortLower: number;
  longUpper: number;
  longLower: number;
}

export interface StockDailyKlineBarDto extends StockKlineBarDto {
  factors: StockKlineBarDto["factors"] & { trendChannel: StockTrendChannelFactorsDto };
}

interface StockDetailKlineFields {
  nineTurnMarkers: NineTurnMarkerDto[];
  pageContext: StockDetailPageContextDto;
  stockRef: {
    tsCode: string;
    name?: string | null;
  };
  adjustment: "forward";
  sourceAdjustment: "qfq";
  quote?: StockQuoteSnapshotDto | null;
  meta: {
    count: number;
    limit: number;
    startDate?: string | null;
    endDate?: string | null;
    nextEndDate?: string | null;
  };
  dataStatus: StockDetailDataStatusDto;
  debugInfo?: unknown;
}

export interface StockDetailDailyKlineResponseDto extends StockDetailKlineFields {
  period: "day";
  bars: StockDailyKlineBarDto[];
}

export interface StockDetailPeriodKlineResponseDto extends StockDetailKlineFields {
  period: "week" | "month";
  bars: StockKlineBarDto[];
}

export type StockDetailKlineResponseDto = StockDetailDailyKlineResponseDto | StockDetailPeriodKlineResponseDto;
