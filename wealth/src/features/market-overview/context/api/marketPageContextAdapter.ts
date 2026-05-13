import type { MarketPageContextResponse } from "./marketPageContextApi";

export interface MarketPageContextViewModel {
  tradeDate: string;
  updateTime: string;
  sessionStatus: "PRE_OPEN" | "TRADING" | "BREAK" | "CLOSED";
}

export function formatPageContextTimestamp(value: string): string {
  const isoLocalMatch = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})/);
  if (isoLocalMatch) return `${isoLocalMatch[1]} ${isoLocalMatch[2]}`;
  return value;
}

export function buildMarketPageContextViewModelFromApi(payload: MarketPageContextResponse): MarketPageContextViewModel {
  return {
    tradeDate: payload.pageContext.tradeDate,
    updateTime: formatPageContextTimestamp(payload.pageContext.generatedAt),
    sessionStatus: payload.pageContext.sessionStatus,
  };
}
