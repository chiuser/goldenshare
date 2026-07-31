import type { StockMinuteFrequency } from "./stockDetailApiTypes";
import type {
  StockMinuteBarDto,
  StockMinuteDataStatusDto,
  StockMinuteIndicatorDto,
  StockMinuteIndicatorsResponseDto,
  StockMinuteBarsResponseDto,
} from "./stockMinuteApiTypes";

export interface StockMinuteChartPoint {
  key: string;
  timestamp: number;
  tradeTime: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  amount: number;
  macdDif: number | null;
  macdDea: number | null;
  macd: number | null;
  kdjK: number | null;
  kdjD: number | null;
  kdjJ: number | null;
}

export interface StockMinuteChartViewModel {
  tsCode: string;
  freq: StockMinuteFrequency;
  points: StockMinuteChartPoint[];
  dataStatus: StockMinuteDataStatusDto;
  indicatorStatus: StockMinuteDataStatusDto;
}

export function buildStockMinuteChartViewModel(
  barsResponse: StockMinuteBarsResponseDto,
  indicatorsResponse: StockMinuteIndicatorsResponseDto,
): StockMinuteChartViewModel {
  const indicatorsByKey = new Map(indicatorsResponse.items.map((item) => [minuteKey(item), item]));
  return {
    tsCode: barsResponse.tsCode,
    freq: barsResponse.freq,
    points: barsResponse.bars.map((bar) => toChartPoint(bar, indicatorsByKey.get(minuteKey(bar)))),
    dataStatus: barsResponse.dataStatus,
    indicatorStatus: indicatorsResponse.dataStatus,
  };
}

export function minuteFrequencyFromPeriodKey(period: string): StockMinuteFrequency | null {
  const match = /^m(1|5|15|30|60|90|120)$/.exec(period);
  if (!match) return null;
  return Number(match[1]) as StockMinuteFrequency;
}

function toChartPoint(bar: StockMinuteBarDto, indicator: StockMinuteIndicatorDto | undefined): StockMinuteChartPoint {
  const timestamp = Date.parse(bar.tradeTime);
  if (!Number.isFinite(timestamp)) throw new Error(`分钟时间字段不合法：${bar.tradeTime}`);
  return {
    key: minuteKey(bar),
    timestamp: Math.floor(timestamp / 1000),
    tradeTime: bar.tradeTime,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    volume: bar.vol,
    amount: bar.amount,
    macdDif: indicator?.macdDif ?? null,
    macdDea: indicator?.macdDea ?? null,
    macd: indicator?.macd ?? null,
    kdjK: indicator?.kdjK ?? null,
    kdjD: indicator?.kdjD ?? null,
    kdjJ: indicator?.kdjJ ?? null,
  };
}

function minuteKey(row: StockMinuteBarDto | StockMinuteIndicatorDto): string {
  const timePart = row.tradeTime.includes("T") ? row.tradeTime.slice(row.tradeTime.indexOf("T") + 1) : row.tradeTime;
  return `${row.tradeDate}T${timePart}`;
}
