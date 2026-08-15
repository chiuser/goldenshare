import type { MarketDirection } from "../../../shared/model/market";

export type IndexDetailDataStatusValue = "READY" | "DELAYED" | "PARTIAL" | "EMPTY";
export type IndexDetailPeriod = "day" | "m1" | "m5" | "m15" | "m30" | "m60" | "m90" | "m120";
export type IndexDetailMinuteFrequency = 1 | 5 | 15 | 30 | 60 | 90 | 120;
export type IndexDetailNineTurnPeriod = "day" | "5" | "15" | "30" | "60" | "90" | "120";

export interface IndexDetailPageContextDto {
  market: "CN_A";
  tradeDate: string;
  prevTradeDate: string | null;
  isTradingDay: boolean;
  sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
  timezone: "Asia/Shanghai";
  generatedAt: string;
  source: "explicit" | "default";
}

export interface IndexDetailDataStatusDto {
  status: IndexDetailDataStatusValue;
  expectedTradeDate: string;
  observedTradeDate: string | null;
}

export interface IndexDetailDebugInfoDto {
  modules: Array<{
    module: "pageInit" | "quote" | "dailyBasic" | "breadth" | "kline" | "weights";
    status: IndexDetailDataStatusValue | "ERROR";
    expectedTradeDate: string;
    observedTradeDate: string | null;
    rowCount: number | null;
    missingCount: number | null;
  }>;
  exceptions: Array<{
    module: "indexDetail" | "indexDetailPageInit" | "indexDetailKline" | "indexDetailWeights";
    code: string;
    severity: "info" | "warn" | "error";
    message: string;
  }>;
}

export interface IndexDetailPageInitResponseDto {
  pageContext: IndexDetailPageContextDto;
  asOfTradeDate: string | null;
  index: {
    tsCode: string;
    name: string;
    market: string | null;
    category: string | null;
    publisher: string | null;
    tags: string[];
  };
  quote: {
    tradeDate: string;
    point: number | null;
    change: number | null;
    changePct: number | null;
    direction: MarketDirection;
    open: number | null;
    high: number | null;
    low: number | null;
    preClose: number | null;
    vol: number | null;
    amount: number | null;
  } | null;
  dailyBasic: {
    tradeDate: string;
    pe: number | null;
    peTtm: number | null;
    pb: number | null;
    turnoverRate: number | null;
    floatMv: number | null;
    totalMv: number | null;
  } | null;
  constituentBreadth: {
    tradeDate: string;
    weightTradeDate: string;
    upCount: number;
    flatCount: number;
    downCount: number;
    totalConstituentCount: number;
    matchedCount: number;
    missingCount: number;
    dataStatus: IndexDetailDataStatusDto;
  } | null;
  chartDefaults: {
    defaultPeriod: "day";
    availablePeriods: IndexDetailPeriod[];
    availableMainOverlays: Array<"MA" | "BOLL" | "TREND_CHANNEL">;
    availableIndicatorTabs: Array<"VOL" | "amount" | "MA" | "MACD" | "KDJ" | "BOLL">;
  };
  capabilities: {
    supportsTimeShare: false;
    supportsWeeklyMonthly: false;
    supportsMinute: boolean;
    minuteFrequencies: IndexDetailMinuteFrequency[];
    supportsTrendChannel: boolean;
    supportsNineTurn: true;
    nineTurnPeriods: IndexDetailNineTurnPeriod[];
    supportsTechnicalConclusion: false;
    supportsTradePlanEntry: true;
  };
  dataStatus: IndexDetailDataStatusDto;
  debugInfo: IndexDetailDebugInfoDto | null;
}

export interface IndexKlineBarDto {
  tradeDate: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  preClose: number | null;
  change: number | null;
  changePct: number | null;
  amplitude: number | null;
  vol: number | null;
  amount: number | null;
  factors: {
    ma: {
      ma5: number | null;
      ma10: number | null;
      ma20: number | null;
      ma30: number | null;
      ma60: number | null;
      ma90: number | null;
      ma250: number | null;
    };
    boll: { upper: number | null; middle: number | null; lower: number | null };
    macd: { dif: number | null; dea: number | null; macd: number | null };
    kdj: { k: number | null; d: number | null; j: number | null };
  };
}

export interface IndexDetailKlineResponseDto {
  pageContext: IndexDetailPageContextDto;
  indexRef: { tsCode: string; name: string | null };
  period: "day";
  bars: IndexKlineBarDto[];
  meta: {
    count: number;
    limit: number;
    startDate: string | null;
    endDate: string | null;
  };
  dataStatus: IndexDetailDataStatusDto;
  debugInfo: IndexDetailDebugInfoDto | null;
}

export interface IndexMinuteDataStatusDto {
  status: "READY" | "DELAYED" | "EMPTY";
  code: "IM_SOURCE_NOT_READY" | null;
  expectedEndDate: string | null;
  observedEndDate: string | null;
  message: string | null;
}

export interface IndexMinuteBarDto {
  tsCode: string;
  freq: IndexDetailMinuteFrequency;
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

export interface IndexMinuteIndicatorDto {
  tsCode: string;
  freq: IndexDetailMinuteFrequency;
  tradeDate: string;
  tradeTime: string;
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
  macdDif: number | null;
  macdDea: number | null;
  macd: number | null;
  kdjK: number | null;
  kdjD: number | null;
  kdjJ: number | null;
  observationCount: number;
  paramsKey: string;
  indicatorVersion: number;
}

export interface IndexMinutesResponseDto {
  tsCode: string;
  freq: IndexDetailMinuteFrequency;
  bars: IndexMinuteBarDto[];
  meta: {
    count: number;
    limit: number;
    hasMore: boolean;
    nextCursor: string | null;
    startDate: string | null;
    endDate: string | null;
    observedStartDate: string | null;
    observedEndDate: string | null;
  };
  dataStatus: IndexMinuteDataStatusDto;
}

export interface IndexMinuteIndicatorsResponseDto {
  tsCode: string;
  freq: IndexDetailMinuteFrequency;
  items: IndexMinuteIndicatorDto[];
  meta: IndexMinutesResponseDto["meta"];
  dataStatus: IndexMinuteDataStatusDto;
}

export interface IndexDetailWeightRowDto {
  conCode: string;
  name: string | null;
  weight: number;
  changePct: number | null;
  contributionPoint: number | null;
  direction: MarketDirection;
}

export interface IndexDetailWeightsResponseDto {
  indexRef: { tsCode: string; name: string | null };
  contributionTradeDate: string;
  weightTradeDate: string | null;
  isEstimated: true;
  rows: IndexDetailWeightRowDto[];
  coverage: {
    totalCount: number;
    returnedCount: number;
    contributionAvailableCount: number;
    contributionMissingCount: number;
    isTruncated: false;
  };
  dataStatus: IndexDetailDataStatusDto;
  note: "基于最新月度权重估算，非指数公司官方归因";
  debugInfo: IndexDetailDebugInfoDto | null;
}
