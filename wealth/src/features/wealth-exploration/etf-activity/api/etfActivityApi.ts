import { wealthFetch } from "../../../../shared/api/wealthApiClient";

export interface EtfActivityTrendPoint {
  tradeDate: string;
  amountYuan: number | null;
  ma5Yuan: number | null;
  ma20Yuan: number | null;
}

export interface EtfActivityRankRow {
  rank: number;
  tsCode: string;
  name: string | null;
  closePrice: number;
  priceChangePct: number;
  amountYuan: number;
  rankChange: number | null;
}

export interface EtfActivityResponse {
  tradeDate: string | null;
  previousTradeDate: string | null;
  oneMonthStartDate: string | null;
  trend: EtfActivityTrendPoint[];
  ranking: {
    status: "ready" | "partial" | "empty" | "error";
    rows: EtfActivityRankRow[];
    error: { code: "ETF_ACTIVITY_RANKING_UNAVAILABLE"; message: string } | null;
  };
}

export async function fetchEtfActivity(signal: AbortSignal): Promise<EtfActivityResponse> {
  const response = await wealthFetch("/api/v1/wealth/market/etf-activity", { method: "GET", signal });
  if (!response.ok) throw new Error(`ETF activity request failed (${response.status})`);
  return await response.json() as EtfActivityResponse;
}
