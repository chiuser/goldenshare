import { wealthFetch } from "../../../../shared/api/wealthApiClient";
import type { NewsReaderMode } from "../../../../shared/ui/news-reader/newsReaderTypes";


export interface NewsReaderItemResponse {
  newsId: string;
  title: string;
  source: string | null;
  publishTime: string;
  readerMode: NewsReaderMode;
  url: string | null;
  html: string | null;
  content: string | null;
}


export class MarketNewsReaderApiError extends Error {
  code: string;
  status: number;

  constructor(message: string, code: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}


export async function fetchMarketNewsReaderItem(
  newsId: string,
  options: { signal?: AbortSignal } = {},
): Promise<NewsReaderItemResponse> {
  const response = await wealthFetch(
    `/api/v1/wealth/market/news/items/${encodeURIComponent(newsId)}`,
    {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: options.signal,
    },
  );
  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    let code = `HTTP_${response.status}`;
    try {
      const payload = (await response.json()) as { code?: string; message?: string };
      if (payload.message) message = payload.message;
      if (payload.code) code = payload.code;
    } catch {
      // Preserve the bounded HTTP error contract when the body is not JSON.
    }
    throw new MarketNewsReaderApiError(message, code, response.status);
  }
  return (await response.json()) as NewsReaderItemResponse;
}
