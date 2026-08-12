import type {
  IndexMinuteBarDto,
  IndexMinuteIndicatorDto,
  IndexMinuteIndicatorsResponseDto,
  IndexMinutesResponseDto,
} from "./indexDetailApiTypes";
import type { IndexMinuteCandlePoint, IndexMinuteChartViewModel } from "../model/indexDetailTypes";

export function buildIndexMinuteChartViewModel(
  barsResponse: IndexMinutesResponseDto,
  indicatorsResponse: IndexMinuteIndicatorsResponseDto,
): IndexMinuteChartViewModel {
  assertMatchingResponseIdentity(barsResponse, indicatorsResponse);
  const bars = [...barsResponse.bars].sort((left, right) => minuteTimestamp(left.tradeTime) - minuteTimestamp(right.tradeTime));
  const indicators = [...indicatorsResponse.items].sort(
    (left, right) => minuteTimestamp(left.tradeTime) - minuteTimestamp(right.tradeTime),
  );
  assertAlignedTimeKeys(bars, indicators, barsResponse);

  const paramsKeys = new Set(indicators.map((item) => item.paramsKey));
  const indicatorVersions = new Set(indicators.map((item) => item.indicatorVersion));
  if (paramsKeys.size !== 1 || indicatorVersions.size !== 1) {
    throw new Error("分钟技术指标参数版本不一致");
  }

  return toViewModel(
    barsResponse,
    bars.map((bar, index) => toPoint(bar, indicators[index]!)),
    "gold",
    indicators[0]!.paramsKey,
    indicators[0]!.indicatorVersion,
  );
}

export function buildIndexMinuteBarsOnlyViewModel(response: IndexMinutesResponseDto): IndexMinuteChartViewModel {
  const bars = [...response.bars].sort((left, right) => minuteTimestamp(left.tradeTime) - minuteTimestamp(right.tradeTime));
  return toViewModel(
    response,
    bars.map((bar) => toPoint(bar, null)),
    "unavailable",
    null,
    null,
  );
}

function assertMatchingResponseIdentity(
  barsResponse: IndexMinutesResponseDto,
  indicatorsResponse: IndexMinuteIndicatorsResponseDto,
): void {
  if (
    barsResponse.tsCode !== indicatorsResponse.tsCode
    || barsResponse.freq !== indicatorsResponse.freq
  ) {
    throw new Error("分钟技术指标与 K 线身份不一致");
  }
}

function assertAlignedTimeKeys(
  bars: IndexMinuteBarDto[],
  indicators: IndexMinuteIndicatorDto[],
  response: IndexMinutesResponseDto,
): void {
  if (bars.length === 0 || bars.length !== indicators.length) {
    throw new Error("分钟技术指标与 K 线数量不一致");
  }
  const seen = new Set<number>();
  bars.forEach((bar, index) => {
    const indicator = indicators[index]!;
    const barTime = minuteTimestamp(bar.tradeTime);
    const indicatorTime = minuteTimestamp(indicator.tradeTime);
    if (
      seen.has(barTime)
      || barTime !== indicatorTime
      || bar.tradeDate !== indicator.tradeDate
      || indicator.tsCode !== response.tsCode
      || indicator.freq !== response.freq
    ) {
      throw new Error("分钟技术指标与 K 线时间键不一致");
    }
    seen.add(barTime);
  });
}

function toViewModel(
  response: IndexMinutesResponseDto,
  points: IndexMinuteCandlePoint[],
  indicatorSource: IndexMinuteChartViewModel["indicatorSource"],
  paramsKey: string | null,
  indicatorVersion: number | null,
): IndexMinuteChartViewModel {
  return {
    tsCode: response.tsCode,
    freq: response.freq,
    points,
    dataStatus: response.dataStatus,
    indicatorSource,
    paramsKey,
    indicatorVersion,
  };
}

function toPoint(
  bar: IndexMinuteBarDto,
  indicator: IndexMinuteIndicatorDto | null,
): IndexMinuteCandlePoint {
  return {
    time: minuteTimestamp(bar.tradeTime),
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

function minuteTimestamp(tradeTime: string): number {
  const timestamp = Date.parse(tradeTime);
  if (!Number.isFinite(timestamp)) throw new Error(`分钟时间字段不合法：${tradeTime}`);
  return Math.floor(timestamp / 1000);
}
