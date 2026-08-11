import type { IndexMinuteBarDto } from "./indexDetailApiTypes";

export const INDEX_MINUTE_MOCK_PARAMS_KEY = "mock_index_minute_technical_v1" as const;
export const INDEX_MINUTE_MOCK_INDICATOR_VERSION = 0 as const;

export interface IndexMinuteMockIndicatorPoint {
  ma5: number | null;
  ma10: number | null;
  ma20: number | null;
  ma30: number | null;
  ma60: number | null;
  ma90: number | null;
  ma250: number | null;
  bollMiddle: number | null;
  bollUpper: number | null;
  bollLower: number | null;
  macdDif: number;
  macdDea: number;
  macd: number;
  kdjK: number | null;
  kdjD: number | null;
  kdjJ: number | null;
  observationCount: number;
}

const maPeriods = [5, 10, 20, 30, 60, 90, 250] as const;

export function buildIndexMinuteMockIndicators(
  bars: IndexMinuteBarDto[],
): IndexMinuteMockIndicatorPoint[] {
  const closes: number[] = [];
  let ema12: number | null = null;
  let ema26: number | null = null;
  let dea: number | null = null;
  let k = 50;
  let d = 50;

  return bars.map((bar, index) => {
    assertFiniteBar(bar);
    closes.push(bar.close);
    const movingAverages = Object.fromEntries(maPeriods.map((period) => [period, average(closes, period)]));
    const bollWindow = closes.length >= 20 ? closes.slice(-20) : null;
    const bollMiddle = bollWindow ? bollWindow.reduce((sum, value) => sum + value, 0) / 20 : null;
    const deviation = bollWindow && bollMiddle !== null
      ? Math.sqrt(bollWindow.reduce((sum, value) => sum + (value - bollMiddle) ** 2, 0) / 20)
      : null;

    ema12 = nextEma(ema12, bar.close, 12);
    ema26 = nextEma(ema26, bar.close, 26);
    const dif = ema12 - ema26;
    dea = nextEma(dea, dif, 9);

    const kdjWindow = index >= 8 ? bars.slice(index - 8, index + 1) : null;
    let nextK: number | null = null;
    let nextD: number | null = null;
    let nextJ: number | null = null;
    if (kdjWindow) {
      const high = Math.max(...kdjWindow.map((item) => item.high));
      const low = Math.min(...kdjWindow.map((item) => item.low));
      const rsv = high === low ? 50 : ((bar.close - low) / (high - low)) * 100;
      k = (2 * k + rsv) / 3;
      d = (2 * d + k) / 3;
      nextK = k;
      nextD = d;
      nextJ = 3 * k - 2 * d;
    }

    return {
      ma5: movingAverages[5] ?? null,
      ma10: movingAverages[10] ?? null,
      ma20: movingAverages[20] ?? null,
      ma30: movingAverages[30] ?? null,
      ma60: movingAverages[60] ?? null,
      ma90: movingAverages[90] ?? null,
      ma250: movingAverages[250] ?? null,
      bollMiddle,
      bollUpper: bollMiddle !== null && deviation !== null ? bollMiddle + 2 * deviation : null,
      bollLower: bollMiddle !== null && deviation !== null ? bollMiddle - 2 * deviation : null,
      macdDif: dif,
      macdDea: dea,
      macd: 2 * (dif - dea),
      kdjK: nextK,
      kdjD: nextD,
      kdjJ: nextJ,
      observationCount: index + 1,
    };
  });
}

function average(values: number[], period: number): number | null {
  if (values.length < period) return null;
  return values.slice(-period).reduce((sum, value) => sum + value, 0) / period;
}

function nextEma(previous: number | null, value: number, period: number): number {
  if (previous === null) return value;
  return previous + (2 / (period + 1)) * (value - previous);
}

function assertFiniteBar(bar: IndexMinuteBarDto): void {
  if ([bar.open, bar.high, bar.low, bar.close, bar.vol, bar.amount].some((value) => !Number.isFinite(value))) {
    throw new Error(`分钟行情包含非法数值：${bar.tradeTime}`);
  }
}
