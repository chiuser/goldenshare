export type StockDetailNewsMatchMethod = "CODE_EXACT" | "FULL_NAME_EXACT" | "SHORT_NAME_EXACT";

export interface StockDetailNewsApiItem {
  newsId: string;
  publishTime: string;
  title: string;
  debugInfo?: {
    matchMethod: StockDetailNewsMatchMethod;
  };
}

export interface StockDetailNewsApiResponse {
  stockRef: {
    tsCode: string;
    name?: string | null;
  };
  items: StockDetailNewsApiItem[];
  meta: {
    count: number;
    limit: number;
    startAt: string;
    endAt: string;
  };
}
