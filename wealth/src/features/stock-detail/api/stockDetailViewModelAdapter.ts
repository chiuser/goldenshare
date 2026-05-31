import { directionFromNumber } from "../../../shared/lib/marketDirection";
import { STOCK_INDICATOR_TABS, STOCK_PERIOD_OPTIONS } from "../model/stockDetailConstants";
import type { StockCandlePoint, StockDetailViewModel, StockPeriodKey } from "../model/stockDetailTypes";
import { getStockDetailViewModel } from "./stockDetailMockAdapter";
import type { StockDetailKlineResponseDto, StockDetailPageInitResponseDto, StockQuoteSnapshotDto } from "./stockDetailApiTypes";

function valueOrZero(value: number | null | undefined): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
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
    volume: valueOrZero(bar.vol),
    amount: valueOrZero(bar.amount),
    ma5: valueOrZero(bar.factors.ma.ma5),
    ma10: valueOrZero(bar.factors.ma.ma10),
    ma20: valueOrZero(bar.factors.ma.ma20),
    ma30: valueOrZero(bar.factors.ma.ma30),
    ma60: valueOrZero(bar.factors.ma.ma60),
    ma90: valueOrZero(bar.factors.ma.ma90),
    ma250: valueOrZero(bar.factors.ma.ma250),
    bollUpper: valueOrZero(bar.factors.boll.upper),
    bollMiddle: valueOrZero(bar.factors.boll.middle),
    bollLower: valueOrZero(bar.factors.boll.lower),
    macd: valueOrZero(bar.factors.macd.macd),
    dif: valueOrZero(bar.factors.macd.dif),
    dea: valueOrZero(bar.factors.macd.dea),
    k: valueOrZero(bar.factors.kdj.k),
    d: valueOrZero(bar.factors.kdj.d),
    j: valueOrZero(bar.factors.kdj.j),
  };
}

function formatVolumeText(vol: number | null | undefined): string {
  const value = valueOrZero(vol);
  if (value >= 10000) return `${(value / 10000).toFixed(2)}万手`;
  return `${Math.round(value)}手`;
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
      volumeText: formatVolumeText(quote.vol),
      amountText: formatAmountText(quote.amount),
    },
    periods: STOCK_PERIOD_OPTIONS.map((period) => ({
      ...period,
      supported: availablePeriods.has(period.key),
    })),
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
