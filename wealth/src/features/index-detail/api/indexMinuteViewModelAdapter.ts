import type { IndexMinuteBarDto, IndexMinutesResponseDto } from "./indexDetailApiTypes";
import {
  buildIndexMinuteMockIndicators,
  INDEX_MINUTE_MOCK_INDICATOR_VERSION,
  INDEX_MINUTE_MOCK_PARAMS_KEY,
} from "./indexMinuteMockIndicatorProvider";
import type { IndexMinuteCandlePoint, IndexMinuteChartViewModel } from "../model/indexDetailTypes";

export function buildIndexMinuteChartViewModel(response: IndexMinutesResponseDto): IndexMinuteChartViewModel {
  const bars = [...response.bars].sort((left, right) => minuteTimestamp(left) - minuteTimestamp(right));
  const indicators = buildIndexMinuteMockIndicators(bars);
  return toViewModel(response, bars.map((bar, index) => toPoint(bar, indicators[index]!)), true);
}

export function buildIndexMinuteBarsOnlyViewModel(response: IndexMinutesResponseDto): IndexMinuteChartViewModel {
  const bars = [...response.bars].sort((left, right) => minuteTimestamp(left) - minuteTimestamp(right));
  return toViewModel(response, bars.map((bar) => toPoint(bar, null)), false);
}

function toViewModel(
  response: IndexMinutesResponseDto,
  points: IndexMinuteCandlePoint[],
  hasMockIndicators: boolean,
): IndexMinuteChartViewModel {
  return {
    tsCode: response.tsCode,
    freq: response.freq,
    points,
    dataStatus: response.dataStatus,
    indicatorSource: hasMockIndicators ? "mock" : "unavailable",
    paramsKey: hasMockIndicators ? INDEX_MINUTE_MOCK_PARAMS_KEY : null,
    indicatorVersion: hasMockIndicators ? INDEX_MINUTE_MOCK_INDICATOR_VERSION : null,
  };
}

function toPoint(
  bar: IndexMinuteBarDto,
  indicator: ReturnType<typeof buildIndexMinuteMockIndicators>[number] | null,
): IndexMinuteCandlePoint {
  return {
    time: minuteTimestamp(bar),
    fullDate: bar.tradeTime,
    open: bar.open,
    high: bar.high,
    low: bar.low,
    close: bar.close,
    preClose: null,
    changePct: null,
    amplitude: null,
    volume: bar.vol,
    amount: bar.amount,
    ma5: indicator?.ma5 ?? null,
    ma10: indicator?.ma10 ?? null,
    ma20: indicator?.ma20 ?? null,
    ma30: indicator?.ma30 ?? null,
    ma60: indicator?.ma60 ?? null,
    ma90: indicator?.ma90 ?? null,
    ma250: indicator?.ma250 ?? null,
    bollUpper: indicator?.bollUpper ?? null,
    bollMiddle: indicator?.bollMiddle ?? null,
    bollLower: indicator?.bollLower ?? null,
    macd: indicator?.macd ?? null,
    dif: indicator?.macdDif ?? null,
    dea: indicator?.macdDea ?? null,
    k: indicator?.kdjK ?? null,
    d: indicator?.kdjD ?? null,
    j: indicator?.kdjJ ?? null,
  };
}

function minuteTimestamp(bar: IndexMinuteBarDto): number {
  const timestamp = Date.parse(bar.tradeTime);
  if (!Number.isFinite(timestamp)) throw new Error(`分钟时间字段不合法：${bar.tradeTime}`);
  return Math.floor(timestamp / 1000);
}
