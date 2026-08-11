import type { IndexDetailKlineResponseDto, IndexDetailPageInitResponseDto } from "../api/indexDetailApiTypes";
import type { TrendChannelRawResponse } from "../api/trendChannelApiClient";

export function makePageInit(tsCode = "000001.SH"): IndexDetailPageInitResponseDto {
  return {
    pageContext: { market: "CN_A", tradeDate: "2026-07-31", prevTradeDate: "2026-07-30", isTradingDay: true, sessionStatus: "CLOSED", timezone: "Asia/Shanghai", generatedAt: "2026-07-31T16:00:00+08:00", source: "explicit" },
    asOfTradeDate: "2026-07-31",
    index: { tsCode, name: tsCode === "000001.SH" ? "上证指数" : "深证成指", market: "CN_A", category: "综合指数", publisher: "交易所", tags: ["主要指数"] },
    quote: { tradeDate: "2026-07-31", point: 3940.04, change: 39.69, changePct: 1.02, direction: "UP", open: 3943.82, high: 3967.59, low: 3938.63, preClose: 3900.35, vol: 542_000_000, amount: 117_000_000 },
    dailyBasic: { tradeDate: "2026-07-31", pe: 17.45, peTtm: 18.12, pb: 1.56, turnoverRate: 1.14, floatMv: 6_194_000_000_000, totalMv: 6_951_000_000_000 },
    constituentBreadth: { tradeDate: "2026-07-31", weightTradeDate: "2026-07-31", upCount: 1711, flatCount: 48, downCount: 593, totalConstituentCount: 2352, matchedCount: 2352, missingCount: 0, dataStatus: readyStatus() },
    chartDefaults: { defaultPeriod: "day", availablePeriods: ["day"], availableMainOverlays: tsCode === "000001.SH" ? ["MA", "BOLL", "TREND_CHANNEL"] : ["MA", "BOLL"], availableIndicatorTabs: ["VOL", "amount", "MA", "MACD", "KDJ", "BOLL"] },
    capabilities: { supportsTimeShare: false, supportsWeeklyMonthly: false, supportsMinute: false, minuteFrequencies: [], supportsTrendChannel: tsCode === "000001.SH", supportsNineTurn: false, supportsTechnicalConclusion: false, supportsTradePlanEntry: true },
    dataStatus: readyStatus(), debugInfo: null,
  };
}

export function makeKline(tsCode = "000001.SH"): IndexDetailKlineResponseDto {
  const pageInit = makePageInit(tsCode);
  return {
    pageContext: pageInit.pageContext, indexRef: { tsCode, name: pageInit.index.name }, period: "day",
    bars: ["2026-07-30", "2026-07-31"].map((tradeDate, index) => ({
      tradeDate, open: 3900 + index * 20, high: 3960 + index * 5, low: 3880 + index * 10, close: 3930 + index * 10, preClose: 3890 + index * 10, change: 40, changePct: 1.02, amplitude: 1.42, vol: 500_000_000, amount: 110_000_000,
      factors: { ma: { ma5: 3900, ma10: 3890, ma20: 3880, ma30: 3870, ma60: 3860, ma90: 3850, ma250: 3800 }, boll: { upper: 4000, middle: 3900, lower: 3800 }, macd: { dif: 1, dea: .5, macd: 1 }, kdj: { k: 60, d: 55, j: 70 } },
    })),
    meta: { count: 2, limit: 300, startDate: "2026-07-30", endDate: "2026-07-31" }, dataStatus: readyStatus(), debugInfo: null,
  };
}

export function makeTrendPayload(): TrendChannelRawResponse {
  return {
    instrument: { ts_code: "000001.SH", name: "上证指数", security_type: "index" }, period: "day", adjustment: "none",
    formula: { key: "high-low-ema-hysteresis", version: "sse-daily-trend-channel-v1", short_period: 25, long_period: 90, seed: "first_observation", state_rule: "strict_close_breakout_inside_retention" },
    data_status: { status: "READY", observed_trade_date: "2026-07-31", as_of_time: "2026-07-31T16:00:00+08:00", is_provisional: false, note: null },
    bars: [rawBar("20260730", "9", "12", "10", "14", "8"), rawBar("20260731", "11", "13", "10", "15", "12")],
    meta: { bar_count: 2, limit: 300, start_date: "2026-07-30", end_date: "2026-07-31", has_more_history: false, next_end_date: null },
  };
}

function rawBar(trade_date: string, close: string, shortUpper: string, shortLower: string, longUpper: string, longLower: string): TrendChannelRawResponse["bars"][number] {
  return { trade_date, open: close, high: shortUpper, low: longLower, close, short_channel: { upper: shortUpper, lower: shortLower, position: "INSIDE", state: "UP" }, long_channel: { upper: longUpper, lower: longLower, position: "INSIDE", state: "UP" }, combined_state: "UP_UP", is_provisional: false };
}

function readyStatus() { return { status: "READY" as const, expectedTradeDate: "2026-07-31", observedTradeDate: "2026-07-31" }; }
