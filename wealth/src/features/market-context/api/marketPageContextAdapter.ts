import type { MarketPageContextResponse } from "./marketPageContextApi";

export interface MarketPageContextViewModel {
  market: "CN_A";
  tradeDate: string;
  prevTradeDate: string | null;
  isTradingDay: boolean;
  sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
  timezone: "Asia/Shanghai";
  generatedAt: string;
  updateTime: string;
  source: "explicit" | "default";
}

export function formatPageContextTimestamp(value: string): string {
  const isoLocalMatch = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
  if (isoLocalMatch) return `${isoLocalMatch[1]} ${isoLocalMatch[2]}`;
  return value;
}

export function buildMarketPageContextViewModelFromApi(
  payload: MarketPageContextResponse,
): MarketPageContextViewModel {
  return {
    market: payload.pageContext.market,
    tradeDate: payload.pageContext.tradeDate,
    prevTradeDate: payload.pageContext.prevTradeDate ?? null,
    isTradingDay: payload.pageContext.isTradingDay,
    sessionStatus: payload.pageContext.sessionStatus,
    timezone: payload.pageContext.timezone,
    generatedAt: payload.pageContext.generatedAt,
    updateTime: formatPageContextTimestamp(payload.pageContext.generatedAt),
    source: payload.pageContext.source,
  };
}
