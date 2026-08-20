import { directionFromNumber } from "../../../shared/lib/marketDirection";
import { STOCK_INDICATOR_TABS, STOCK_PERIOD_OPTIONS } from "../model/stockDetailConstants";
import type { StockCandlePoint, StockDetailViewModel, StockPeriodKey } from "../model/stockDetailTypes";
import { getStockDetailViewModel } from "./stockDetailMockAdapter";
import type { StockDetailKlineResponseDto, StockDetailPageInitResponseDto, StockQuoteSnapshotDto } from "./stockDetailApiTypes";
import { minuteFrequencyFromPeriodKey } from "./stockMinuteViewModelAdapter";

function valueOrZero(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function finiteOrNull(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function resolveDirection(quote: StockQuoteSnapshotDto) {
  if (quote.direction === "UP" || quote.direction === "DOWN" || quote.direction === "FLAT") return quote.direction;
  return directionFromNumber(valueOrZero(quote.changePct));
}

function toCandlePoint(bar: StockDetailKlineResponseDto["bars"][number]): StockCandlePoint {
  return {
    time: bar.tradeDate,
    fullDate: bar.tradeDate,
    open: valueOrZero(bar.open),
    high: valueOrZero(bar.high),
    low: valueOrZero(bar.low),
    close: valueOrZero(bar.close),
    preClose: valueOrZero(bar.preClose),
    changePct: valueOrZero(bar.changePct),
    amplitude: valueOrZero(bar.amplitude),
    volume: valueOrZero(bar.vol),
    volumeDisplay: bar.volDisplay,
    amount: valueOrZero(bar.amount),
    turnoverRate: valueOrZero(bar.turnoverRate),
    volumeRatio: valueOrZero(bar.volumeRatio),
    ma5: finiteOrNull(bar.factors.ma.ma5),
    ma10: finiteOrNull(bar.factors.ma.ma10),
    ma20: finiteOrNull(bar.factors.ma.ma20),
    ma30: finiteOrNull(bar.factors.ma.ma30),
    ma60: finiteOrNull(bar.factors.ma.ma60),
    ma90: finiteOrNull(bar.factors.ma.ma90),
    ma250: finiteOrNull(bar.factors.ma.ma250),
    bollUpper: valueOrZero(bar.factors.boll.upper),
    bollMiddle: valueOrZero(bar.factors.boll.middle),
    bollLower: valueOrZero(bar.factors.boll.lower),
    macd: finiteOrNull(bar.factors.macd.macd),
    dif: finiteOrNull(bar.factors.macd.dif),
    dea: finiteOrNull(bar.factors.macd.dea),
    k: finiteOrNull(bar.factors.kdj.k),
    d: finiteOrNull(bar.factors.kdj.d),
    j: finiteOrNull(bar.factors.kdj.j),
  };
}

function formatAmountText(amount: number | null | undefined): string {
  const value = valueOrZero(amount);
  if (value >= 100000) return `${(value / 100000).toFixed(2)}亿`;
  return `${value.toFixed(2)}万`;
}

export function buildStockDetailViewModel(
  pageInit: StockDetailPageInitResponseDto,
  kline: StockDetailKlineResponseDto,
): StockDetailViewModel {
  if (!pageInit.quote) {
    throw new Error("暂无股票行情数据");
  }
  if (kline.bars.length === 0) {
    throw new Error("暂无股票K线数据");
  }

  const scaffold = getStockDetailViewModel(pageInit.stock.tsCode);
  const availablePeriods = new Set<StockPeriodKey>(pageInit.chartDefaults.availablePeriods);
  const minuteFrequencies = new Set(pageInit.capabilities.minuteFrequencies ?? []);
  const availableIndicators = new Set<string>(pageInit.chartDefaults.availableIndicatorTabs);
  const quote = pageInit.quote;

  return {
    ...scaffold,
    stock: {
      tsCode: pageInit.stock.tsCode,
      name: pageInit.stock.name,
      market: pageInit.stock.market ?? "CN_A",
      sector: pageInit.stock.industry ?? pageInit.stock.area ?? "--",
      tags: pageInit.stock.tags.length > 0 ? pageInit.stock.tags : [pageInit.stock.industry ?? "股票"].filter(Boolean),
    },
    quote: {
      price: valueOrZero(quote.price),
      change: valueOrZero(quote.change),
      changePct: valueOrZero(quote.changePct),
      direction: resolveDirection(quote),
      open: valueOrZero(quote.open),
      prevClose: valueOrZero(quote.preClose),
      high: valueOrZero(quote.high),
      low: valueOrZero(quote.low),
      turnoverRate: valueOrZero(quote.turnoverRate),
      volumeRatio: valueOrZero(quote.volumeRatio),
      volumeText: quote.volDisplay ?? "--",
      amountText: formatAmountText(quote.amount),
    },
    periods: STOCK_PERIOD_OPTIONS.map((period) => {
      const minuteFrequency = minuteFrequencyFromPeriodKey(period.key);
      return {
        ...period,
        supported:
          availablePeriods.has(period.key) ||
          (pageInit.capabilities.supportsMinute && minuteFrequency !== null && minuteFrequencies.has(minuteFrequency)),
      };
    }),
    activePeriod: pageInit.chartDefaults.defaultPeriod,
    chart: {
      candles: kline.bars.map(toCandlePoint),
    },
    indicatorTabs: STOCK_INDICATOR_TABS.map((tab) => ({
      ...tab,
      supported: tab.supported && availableIndicators.has(tab.key),
    })),
  };
}
