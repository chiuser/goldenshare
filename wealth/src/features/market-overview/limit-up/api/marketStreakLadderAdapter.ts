import type { LadderV5, LadderV5PromotionLayer, LadderV5Stock } from "../../api/marketOverviewTypes";
import type { MarketStreakLadderResponse } from "./marketStreakLadderApi";

function toStock(item: {
  stockName?: string | null;
  stockCode: string;
  latestPrice?: number | null;
  changePct?: number | null;
  sectorName?: string | null;
  openTimes?: number | null;
  currentStreakLevel: number;
  advanced: boolean;
}): LadderV5Stock {
  return {
    stockName: item.stockName?.trim() || item.stockCode,
    stockCode: item.stockCode,
    latestPrice: typeof item.latestPrice === "number" ? item.latestPrice : 0,
    changePct: typeof item.changePct === "number" ? item.changePct : 0,
    sectorName: item.sectorName?.trim() || "--",
    openTimes: typeof item.openTimes === "number" ? item.openTimes : 0,
    currentStreakLevel: item.currentStreakLevel,
    advanced: item.advanced,
  };
}

function toPromotionLayer(layer: {
  previousLabel: string;
  currentLabel: string;
  previousStocks: Array<{
    stockName?: string | null;
    stockCode: string;
    latestPrice?: number | null;
    changePct?: number | null;
    sectorName?: string | null;
    openTimes?: number | null;
    currentStreakLevel: number;
    advanced: boolean;
  }>;
  currentStocks: Array<{
    stockName?: string | null;
    stockCode: string;
    latestPrice?: number | null;
    changePct?: number | null;
    sectorName?: string | null;
    openTimes?: number | null;
    currentStreakLevel: number;
    advanced: boolean;
  }>;
}): LadderV5PromotionLayer {
  return {
    previousLabel: layer.previousLabel,
    currentLabel: layer.currentLabel,
    previousStocks: layer.previousStocks.map(toStock),
    currentStocks: layer.currentStocks.map(toStock),
  };
}

export function buildStreakLadderViewModelFromApi(payload: MarketStreakLadderResponse): LadderV5 {
  const promotions: Record<number, LadderV5PromotionLayer> = {};
  Object.entries(payload.streakLadderV5.promotions).forEach(([key, value]) => {
    const numericKey = Number(key);
    if (Number.isFinite(numericKey)) {
      promotions[numericKey] = toPromotionLayer(value);
    }
  });

  return {
    tradeDate: payload.streakLadderV5.tradeDate,
    prevTradeDate: payload.streakLadderV5.prevTradeDate,
    highestStreakLevel: payload.streakLadderV5.highestStreakLevel,
    aboveFive: payload.streakLadderV5.aboveFive.map(toStock),
    promotions,
    firstBoard: payload.streakLadderV5.firstBoard.map(toStock),
  };
}
