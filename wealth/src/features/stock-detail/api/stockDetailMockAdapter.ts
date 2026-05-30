import { directionFromNumber } from "../../../shared/lib/marketDirection";
import type { StockCandlePoint, StockDetailViewModel } from "../model/stockDetailTypes";
import { STOCK_INDICATOR_TABS, STOCK_PERIOD_OPTIONS } from "../model/stockDetailConstants";

function round(value: number, digits = 2): number {
  return Number(value.toFixed(digits));
}

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function movingAverage(closes: number[], index: number, size: number): number {
  const start = Math.max(0, index - size + 1);
  return round(average(closes.slice(start, index + 1)));
}

function formatDate(date: Date): string {
  const yyyy = date.getFullYear();
  const mm = `${date.getMonth() + 1}`.padStart(2, "0");
  const dd = `${date.getDate()}`.padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function generateCandleSeries(): StockCandlePoint[] {
  const baseDate = new Date(2025, 9, 13);
  const raw = Array.from({ length: 150 }, (_, index) => {
    const date = new Date(baseDate);
    date.setDate(baseDate.getDate() + index);
    const wave = Math.sin(index / 7) * 0.58 + Math.cos(index / 13) * 0.28;
    const drift = index * 0.018;
    const close = round(15.92 + drift + wave);
    const open = round(close + Math.sin(index / 5) * 0.23);
    const high = round(Math.max(open, close) + 0.22 + Math.abs(Math.sin(index / 6)) * 0.42);
    const low = round(Math.min(open, close) - 0.18 - Math.abs(Math.cos(index / 8)) * 0.3);
    const volume = Math.round(64000 + Math.abs(Math.sin(index / 4)) * 52000 + (index % 11) * 2600);
    return {
      time: formatDate(date),
      fullDate: formatDate(date),
      open,
      high,
      low,
      close,
      volume,
      amount: round((volume * close) / 10000, 2),
    };
  });

  const closes = raw.map((row) => row.close);

  return raw.map((row, index) => {
    const ma5 = movingAverage(closes, index, 5);
    const ma15 = movingAverage(closes, index, 15);
    const ma30 = movingAverage(closes, index, 30);
    const ma60 = movingAverage(closes, index, 60);
    const ma120 = movingAverage(closes, index, 120);
    const ma250 = movingAverage(closes, index, 250);
    const volatility = 0.8 + Math.abs(Math.sin(index / 11)) * 0.42;
    const dif = round(Math.sin(index / 9) * 0.42);
    const dea = round(Math.cos(index / 10) * 0.28);

    return {
      ...row,
      ma5,
      ma15,
      ma30,
      ma60,
      ma120,
      ma250,
      bollUpper: round(ma30 + volatility),
      bollMiddle: ma30,
      bollLower: round(ma30 - volatility),
      macd: round((dif - dea) * 2),
      dif,
      dea,
      k: round(47 + Math.sin(index / 6) * 23),
      d: round(45 + Math.cos(index / 7) * 18),
      j: round(50 + Math.sin(index / 5) * 31),
    };
  });
}

export function getStockDetailViewModel(tsCode: string): StockDetailViewModel {
  const candles = generateCandleSeries();
  const latest = candles.at(-1);
  const previous = candles.at(-2);
  if (!latest || !previous) {
    throw new Error("股票详情页 mock 数据不可用");
  }
  const change = round(latest.close - previous.close);
  const changePct = round((change / previous.close) * 100);

  return {
    topMarketTickers: [
      { code: "000001.SH", name: "上证指数", point: 4177.92, pct: -1.52, direction: "DOWN" },
      { code: "399001.SZ", name: "深证成指", point: 15745.74, pct: -2.14, direction: "DOWN" },
      { code: "399006.SZ", name: "创业板指", point: 3951.14, pct: -2.16, direction: "DOWN" },
      { code: "000688.SH", name: "科创50", point: 1725.09, pct: -2.55, direction: "DOWN" },
      { code: "000300.SH", name: "沪深300", point: 4914.6, pct: -1.68, direction: "DOWN" },
      { code: "000905.SH", name: "中证500", point: 8670.16, pct: -2.78, direction: "DOWN" },
      { code: "000852.SH", name: "中证1000", point: 8778.71, pct: -1.97, direction: "DOWN" },
      { code: "899050.BJ", name: "北证50", point: 1384.78, pct: -3.73, direction: "DOWN" },
      { code: "000510.SH", name: "中证A500", point: 6182.97, pct: -2.14, direction: "DOWN" },
      { code: "000016.SH", name: "上证50", point: 2996.57, pct: -1.66, direction: "DOWN" },
    ],
    stock: {
      tsCode,
      name: "福斯特",
      market: "CN_A",
      sector: "光伏设备",
      tags: ["光伏设备", "新材料"],
    },
    quote: {
      price: 18.36,
      change,
      changePct,
      direction: directionFromNumber(change),
      open: 18.1,
      prevClose: 18.01,
      high: 18.66,
      low: 17.98,
      turnoverRate: 1.24,
      volumeRatio: 1.18,
      volumeText: "12.86万手",
      amountText: "2.37亿",
    },
    periods: STOCK_PERIOD_OPTIONS,
    activePeriod: "day",
    chart: { candles },
    indicatorTabs: STOCK_INDICATOR_TABS,
    rightRail: {
      sectors: [
        { name: "光伏设备", pct: 2.36, count: 126, type: "行业", direction: "UP" },
        { name: "新能源", pct: 1.58, count: 238, type: "概念", direction: "UP" },
        { name: "浙江板块", pct: -0.42, count: 692, type: "地域", direction: "DOWN" },
        { name: "胶膜材料", pct: 3.12, count: 18, type: "题材", direction: "UP" },
      ],
      moneyFlow: [
        { label: "净特大", value: 1260, direction: "UP", ratio: 72 },
        { label: "净大单", value: 980, direction: "UP", ratio: 56 },
        { label: "净中单", value: -520, direction: "DOWN", ratio: 38 },
        { label: "净小单", value: -1720, direction: "DOWN", ratio: 84 },
      ],
      productBoundaryNotes: [
        "首版仅展示 mock 行情与 UI 交互，不接真实交易能力。",
        "诊股、交易计划、更多指标暂未开通，点击仅提示。",
      ],
    },
  };
}
