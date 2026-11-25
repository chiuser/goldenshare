import { adaptNineTurnSeries } from "../../nine-turn/model/nineTurnAdapter";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import type { StockMinuteFrequency } from "./stockDetailApiTypes";
import type {
  StockMinuteBarDto,
  StockMinuteDataStatusDto,
  StockMinuteIndicatorDto,
  StockMinuteChartResponseDto,
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
  nineTurnLayer: NineTurnLayerViewModel | null;
}

export function buildStockMinuteChartViewModel(
  response: StockMinuteChartResponseDto,
): StockMinuteChartViewModel {
  assertMatchingResponseIdentity(response);
  const barsByKey = uniqueRowsByMinuteKey(response.bars, "K 线");
  const indicatorsByKey = uniqueRowsByMinuteKey(response.indicators, "技术指标");
  if (
    barsByKey.size !== indicatorsByKey.size
    || [...barsByKey.keys()].some((key) => !indicatorsByKey.has(key))
  ) {
    throw new Error("分钟技术指标与 K 线时间键不一致");
  }

  return {
    tsCode: response.tsCode,
    freq: response.freq,
    points: response.bars.map((bar) => toChartPoint(bar, indicatorsByKey.get(minuteKey(bar))!)),
    dataStatus: response.dataStatus,
    nineTurnLayer: response.nineTurn ? adaptNineTurnSeries(response.nineTurn, {
      period: String(response.freq) as "30" | "60" | "90" | "120",
      subjectType: "stock",
      tsCode: response.tsCode,
    }) : null,
  };
}

export function minuteFrequencyFromPeriodKey(period: string): StockMinuteFrequency | null {
  const match = /^m(1|5|15|30|60|90|120)$/.exec(period);
  if (!match) return null;
  return Number(match[1]) as StockMinuteFrequency;
}

function assertMatchingResponseIdentity(response: StockMinuteChartResponseDto): void {
  if (
    response.bars.some((bar) => bar.tsCode !== response.tsCode || bar.freq !== response.freq)
    || response.indicators.some((item) => item.tsCode !== response.tsCode || item.freq !== response.freq)
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
