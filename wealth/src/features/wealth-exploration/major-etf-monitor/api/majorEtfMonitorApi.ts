import { wealthFetch } from "../../../../shared/api/wealthApiClient";

export interface MajorEtfTrendPoint {
  tradeDate: string;
  amountYuan: number | null;
}

export interface MajorEtfQuote {
  tsCode: string;
  name: string | null;
  closePrice: number | null;
  priceChangePct: number | null;
  amountYuan: number | null;
}

export interface MajorEtfMonitorResponse {
  status: "ready" | "empty";
  tradeDate: string | null;
  oneMonthStartDate: string | null;
  trend: MajorEtfTrendPoint[];
  quotes: MajorEtfQuote[];
}

export async function fetchMajorEtfMonitor(signal: AbortSignal): Promise<MajorEtfMonitorResponse> {
  const response = await wealthFetch("/api/v1/wealth/market/major-etf-monitor", { method: "GET", signal });
  if (!response.ok) throw new Error(`Major ETF monitor request failed (${response.status})`);
  return await response.json() as MajorEtfMonitorResponse;
}
