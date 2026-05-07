export type MarketDirection = "UP" | "DOWN" | "FLAT" | "UNKNOWN";

export type DataStatus = "READY" | "DELAYED" | "PARTIAL" | "EMPTY" | "ERROR";

export interface TrendPoint {
  label: string;
  value: number;
}

export interface MultiTrendPoint {
  label: string;
  [key: string]: string | number;
}
