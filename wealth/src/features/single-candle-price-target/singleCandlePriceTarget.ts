export type PriceTargetDirection = "top" | "bottom";

export interface PriceTargetAsset {
  kind: "stock" | "index";
  tsCode: string;
  name: string;
}

interface DailyCandle {
  tradeDate: string;
  open?: number | null;
  high?: number | null;
  low?: number | null;
  close?: number | null;
  changePct?: number | null;
}

export interface PriceTargetQuote {
  current: DailyCandle;
  previous: Pick<DailyCandle, "tradeDate" | "close"> | null;
}

export const priceTargetTitles = { top: "单阳测顶", bottom: "单阴测底" } as const;

export const defaultPriceTargetCoefficients = {
  stock: { top: "0.85", bottom: "1.15" },
  index: { top: "0.90", bottom: "1.10" },
} as const;

export function selectPriceTargetQuote(bars: readonly DailyCandle[], date: string): PriceTargetQuote | null {
  let current: DailyCandle | undefined;
  let previous: DailyCandle | null = null;
  for (const bar of bars) {
    if (bar.tradeDate === date) current = bar;
    if (bar.tradeDate < date && (!previous || bar.tradeDate > previous.tradeDate)) previous = bar;
  }
  return current ? { current, previous } : null;
}

export function isPositivePriceTargetNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

export function calculatePriceTarget(close: number, previousClose: number, coefficient: number): number | null {
  const result = close * close / (previousClose * coefficient);
  return isPositivePriceTargetNumber(result) ? result : null;
}

const numberFormat = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function formatPriceTargetNumber(value: number | null | undefined): string {
  return typeof value === "number" && Number.isFinite(value) ? numberFormat.format(value) : "--";
}
