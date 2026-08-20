import { directionClass } from "../../../shared/lib/marketDirection";
import type { MarketDirection } from "../../../shared/model/market";
import type { IndexDetailKlineResponseDto, IndexDetailPageInitResponseDto } from "./indexDetailApiTypes";
import { INDEX_INDICATOR_TABS, INDEX_PERIOD_OPTIONS } from "../model/indexDetailConstants";
import type {
  IndexBasicMetric,
  IndexCandlePoint,
  IndexDetailViewModel,
  IndexPeriodKey,
} from "../model/indexDetailTypes";

export function buildIndexDetailViewModel(
  pageInit: IndexDetailPageInitResponseDto,
  kline: IndexDetailKlineResponseDto,
): IndexDetailViewModel {
  if (!pageInit.quote || !pageInit.asOfTradeDate || kline.bars.length === 0) {
    throw new Error("指数详情缺少可展示的日线行情");
  }

  const availableIndicators = new Set(pageInit.chartDefaults.availableIndicatorTabs);
  return {
    pageContext: pageInit.pageContext,
    asOfTradeDate: pageInit.asOfTradeDate,
    identity: pageInit.index,
    quote: {
      point: pageInit.quote.point,
      change: pageInit.quote.change,
      changePct: pageInit.quote.changePct,
      direction: pageInit.quote.direction,
    },
    basicMetrics: buildBasicMetrics(pageInit),
    periods: INDEX_PERIOD_OPTIONS.map((period) => ({
      ...period,
      supported: supportsPeriod(pageInit, period.key),
    })),
    indicatorTabs: INDEX_INDICATOR_TABS.map((tab) => ({
      ...tab,
      supported: availableIndicators.has(tab.key),
    })),
    chart: { candles: kline.bars.map(toCandlePoint) },
    capabilities: pageInit.capabilities,
    dataStatus: mergeDataStatus(pageInit, kline),
  };
}

export function buildEmptyIndexDetailViewModel(pageInit: IndexDetailPageInitResponseDto): IndexDetailViewModel {
  return {
    pageContext: pageInit.pageContext,
    asOfTradeDate: null,
    identity: pageInit.index,
    quote: { point: null, change: null, changePct: null, direction: "UNKNOWN" },
    basicMetrics: buildBasicMetrics({
      ...pageInit,
      quote: null,
      dailyBasic: null,
      constituentBreadth: null,
    }),
    periods: INDEX_PERIOD_OPTIONS.map((period) => ({ ...period, supported: period.key === "day" })),
    indicatorTabs: INDEX_INDICATOR_TABS.map((tab) => ({ ...tab, supported: false })),
    chart: { candles: [] },
    capabilities: pageInit.capabilities,
    dataStatus: pageInit.dataStatus,
  };
}

function supportsPeriod(pageInit: IndexDetailPageInitResponseDto, period: IndexPeriodKey): boolean {
  if (period === "day") return true;
  if (!import.meta.env.DEV || !pageInit.capabilities.supportsMinute) return false;
  const match = /^m(1|5|15|30|60|90|120)$/.exec(period);
  if (!match) return false;
  return pageInit.capabilities.minuteFrequencies.includes(Number(match[1]) as 1 | 5 | 15 | 30 | 60 | 90 | 120);
}

export function buildBasicMetrics(pageInit: IndexDetailPageInitResponseDto): IndexBasicMetric[] {
  const quote = pageInit.quote;
  const basic = pageInit.dailyBasic;
  const breadth = pageInit.constituentBreadth;
  return [
    metric("preClose", "昨收", quote?.preClose, formatFixed, "secondary"),
    metric("open", "今开", quote?.open, formatFixed, compareTone(quote?.open, quote?.preClose)),
    displayMetric("vol", "总量", quote?.volDisplay, "secondary"),
    metric("high", "最高", quote?.high, formatFixed, compareTone(quote?.high, quote?.preClose)),
    metric("low", "最低", quote?.low, formatFixed, compareTone(quote?.low, quote?.preClose)),
    metric("amount", "金额", quote?.amount, formatAmountFromThousandYuan, "secondary"),
    metric("pe", "市盈率", basic?.pe, formatFixed, "secondary"),
    metric("peTtm", "TTM 市盈率", basic?.peTtm, formatFixed, "secondary"),
    metric("pb", "市净率", basic?.pb, formatFixed, "secondary"),
    metric("turnoverRate", "换手率", basic?.turnoverRate, formatPercent, "secondary"),
    metric("floatMv", "流通市值", basic?.floatMv, formatYuan, "secondary"),
    metric("totalMv", "总市值", basic?.totalMv, formatYuan, "secondary"),
    metric("upCount", "上涨数", breadth?.upCount, formatInteger, "up"),
    metric("flatCount", "平盘数", breadth?.flatCount, formatInteger, "flat"),
    metric("downCount", "下跌数", breadth?.downCount, formatInteger, "down"),
  ];
}

export function formatNullablePoint(value: number | null | undefined): string {
  return isFiniteNumber(value) ? value.toFixed(2) : "--";
}

export function formatNullableSignedPoint(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}`;
}

export function formatNullableSignedPercent(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
}

export function marketDirectionClass(direction: MarketDirection): string {
  return directionClass(direction);
}

function toCandlePoint(bar: IndexDetailKlineResponseDto["bars"][number]): IndexCandlePoint {
  return {
    time: toIsoDate(bar.tradeDate),
    fullDate: toIsoDate(bar.tradeDate),
    open: finiteOrNull(bar.open),
    high: finiteOrNull(bar.high),
    low: finiteOrNull(bar.low),
    close: finiteOrNull(bar.close),
    preClose: finiteOrNull(bar.preClose),
    changePct: finiteOrNull(bar.changePct),
    amplitude: finiteOrNull(bar.amplitude),
    volume: finiteOrNull(bar.vol),
    volumeDisplay: bar.volDisplay,
    amount: finiteOrNull(bar.amount),
    ma5: finiteOrNull(bar.factors.ma.ma5),
    ma10: finiteOrNull(bar.factors.ma.ma10),
    ma20: finiteOrNull(bar.factors.ma.ma20),
    ma30: finiteOrNull(bar.factors.ma.ma30),
    ma60: finiteOrNull(bar.factors.ma.ma60),
    ma90: finiteOrNull(bar.factors.ma.ma90),
    ma250: finiteOrNull(bar.factors.ma.ma250),
    bollUpper: finiteOrNull(bar.factors.boll.upper),
    bollMiddle: finiteOrNull(bar.factors.boll.middle),
    bollLower: finiteOrNull(bar.factors.boll.lower),
    macd: finiteOrNull(bar.factors.macd.macd),
    dif: finiteOrNull(bar.factors.macd.dif),
    dea: finiteOrNull(bar.factors.macd.dea),
    k: finiteOrNull(bar.factors.kdj.k),
    d: finiteOrNull(bar.factors.kdj.d),
    j: finiteOrNull(bar.factors.kdj.j),
  };
}

function metric(
  key: string,
  label: string,
  value: number | null | undefined,
  formatter: (value: number | null | undefined) => string,
  tone: IndexBasicMetric["tone"],
): IndexBasicMetric {
  return { key, label, value: formatter(value), tone };
}

function displayMetric(
  key: string,
  label: string,
  value: string | null | undefined,
  tone: IndexBasicMetric["tone"],
): IndexBasicMetric {
  return { key, label, value: value ?? "--", tone };
}

function compareTone(value: number | null | undefined, base: number | null | undefined): IndexBasicMetric["tone"] {
  if (!isFiniteNumber(value) || !isFiniteNumber(base)) return "secondary";
  if (value > base) return "up";
  if (value < base) return "down";
  return "flat";
}

function formatFixed(value: number | null | undefined): string {
  return isFiniteNumber(value) ? value.toFixed(2) : "--";
}

function formatPercent(value: number | null | undefined): string {
  return isFiniteNumber(value) ? `${value.toFixed(2)}%` : "--";
}

function formatInteger(value: number | null | undefined): string {
  return isFiniteNumber(value) ? Math.round(value).toLocaleString("zh-CN") : "--";
}

function formatAmountFromThousandYuan(value: number | null | undefined): string {
  return isFiniteNumber(value) ? formatYuan(value * 1_000) : "--";
}

function formatYuan(value: number | null | undefined): string {
  if (!isFiniteNumber(value)) return "--";
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000_000_000) return `${(value / 1_000_000_000_000).toFixed(2)}万亿`;
  if (absolute >= 100_000_000) return `${(value / 100_000_000).toFixed(2)}亿`;
  if (absolute >= 10_000) return `${(value / 10_000).toFixed(2)}万`;
  return `${value.toFixed(2)}`;
}

function finiteOrNull(value: number | null): number | null {
  return Number.isFinite(value) ? value : null;
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function toIsoDate(value: string): string {
  if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  return value;
}

function mergeDataStatus(
  pageInit: IndexDetailPageInitResponseDto,
  kline: IndexDetailKlineResponseDto,
): IndexDetailKlineResponseDto["dataStatus"] {
  if (pageInit.dataStatus.status === "PARTIAL") return pageInit.dataStatus;
  if (kline.dataStatus.status === "PARTIAL") return kline.dataStatus;
  if (pageInit.dataStatus.status === "DELAYED") return pageInit.dataStatus;
  if (kline.dataStatus.status === "DELAYED") return kline.dataStatus;
  return kline.dataStatus;
}
