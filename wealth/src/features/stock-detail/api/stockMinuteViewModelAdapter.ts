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
  assertMatchingResponseIdentity(barsResponse, indicatorsResponse);
  const barsByKey = uniqueRowsByMinuteKey(barsResponse.bars, "K 线");
  const indicatorsByKey = uniqueRowsByMinuteKey(indicatorsResponse.items, "技术指标");
  if (
    barsByKey.size !== indicatorsByKey.size
    || [...barsByKey.keys()].some((key) => !indicatorsByKey.has(key))
  ) {
    throw new Error("分钟技术指标与 K 线时间键不一致");
  }

  return {
    tsCode: barsResponse.tsCode,
    freq: barsResponse.freq,
    points: barsResponse.bars.map((bar) => toChartPoint(bar, indicatorsByKey.get(minuteKey(bar))!)),
    dataStatus: barsResponse.dataStatus,
    indicatorStatus: indicatorsResponse.dataStatus,
  };
}

export function minuteFrequencyFromPeriodKey(period: string): StockMinuteFrequency | null {
  const match = /^m(1|5|15|30|60|90|120)$/.exec(period);
  if (!match) return null;
  return Number(match[1]) as StockMinuteFrequency;
}

function assertMatchingResponseIdentity(
  barsResponse: StockMinuteBarsResponseDto,
  indicatorsResponse: StockMinuteIndicatorsResponseDto,
): void {
  if (
    barsResponse.tsCode !== indicatorsResponse.tsCode
    || barsResponse.freq !== indicatorsResponse.freq
  ) {
    throw new Error("分钟技术指标与 K 线身份不一致");
  }
  if (
    barsResponse.bars.some((bar) => bar.tsCode !== barsResponse.tsCode || bar.freq !== barsResponse.freq)
    || indicatorsResponse.items.some(
      (item) => item.tsCode !== indicatorsResponse.tsCode || item.freq !== indicatorsResponse.freq,
    )
  ) {
    throw new Error("分钟响应行身份与根级身份不一致");
  }
}

function uniqueRowsByMinuteKey<T extends StockMinuteBarDto | StockMinuteIndicatorDto>(
  rows: T[],
  label: string,
): Map<string, T> {
  const rowsByKey = new Map<string, T>();
  rows.forEach((row) => {
    const key = minuteKey(row);
    if (rowsByKey.has(key)) throw new Error(`分钟${label}存在重复时间键`);
    rowsByKey.set(key, row);
  });
  return rowsByKey;
}

function toChartPoint(bar: StockMinuteBarDto, indicator: StockMinuteIndicatorDto): StockMinuteChartPoint {
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
    macdDif: indicator.macdDif,
    macdDea: indicator.macdDea,
    macd: indicator.macd,
    kdjK: indicator.kdjK,
    kdjD: indicator.kdjD,
    kdjJ: indicator.kdjJ,
  };
}

function minuteKey(row: StockMinuteBarDto | StockMinuteIndicatorDto): string {
  const timePart = row.tradeTime.includes("T") ? row.tradeTime.slice(row.tradeTime.indexOf("T") + 1) : row.tradeTime;
  return `${row.tradeDate}T${timePart}`;
}
