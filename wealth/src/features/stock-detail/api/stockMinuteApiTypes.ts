import type { StockMinuteFrequency } from "./stockDetailApiTypes";

export type { StockMinuteFrequency } from "./stockDetailApiTypes";

export type StockMinuteDataStatus = "READY" | "DELAYED" | "EMPTY" | "ERROR";

export interface StockMinutePageMeta {
  count: number;
  limit: number;
  hasMore: boolean;
  nextCursor?: string | null;
  startDate?: string | null;
  endDate?: string | null;
  observedStartDate?: string | null;
  observedEndDate?: string | null;
}

export interface StockMinuteDataStatusDto {
  status: StockMinuteDataStatus;
  expectedEndDate?: string | null;
  observedEndDate?: string | null;
  message?: string | null;
}

export interface StockMinuteBarDto {
  tsCode: string;
  freq: StockMinuteFrequency;
  tradeDate: string;
  tradeTime: string;
  open: number;
  high: number;
  low: number;
  close: number;
  vol: number;
  amount: number;
  exchange: string;
}

export interface StockMinuteIndicatorDto {
  tsCode: string;
  freq: StockMinuteFrequency;
  tradeDate: string;
  tradeTime: string;
  macdDif: number | null;
  macdDea: number | null;
  macd: number | null;
  kdjK: number | null;
  kdjD: number | null;
  kdjJ: number | null;
  paramsKey: string;
  indicatorVersion: number;
}

export interface StockMinuteBarsResponseDto {
  tsCode: string;
  freq: StockMinuteFrequency;
  bars: StockMinuteBarDto[];
  meta: StockMinutePageMeta;
  dataStatus: StockMinuteDataStatusDto;
  debugInfo?: unknown;
}

export interface StockMinuteIndicatorsResponseDto {
  tsCode: string;
  freq: StockMinuteFrequency;
  items: StockMinuteIndicatorDto[];
  meta: StockMinutePageMeta;
  dataStatus: StockMinuteDataStatusDto;
  debugInfo?: unknown;
}
