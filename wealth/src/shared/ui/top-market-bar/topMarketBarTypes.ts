import type { MarketDirection } from "../../model/market";

export interface TopMarketTicker {
  code: string;
  name: string;
  point: number;
  change?: number;
  pct: number;
  direction: MarketDirection;
}

export type TopMarketNavKey =
  | "market"
  | "exploration"
  | "assistant"
  | "training"
  | "data"
  | "settings";
