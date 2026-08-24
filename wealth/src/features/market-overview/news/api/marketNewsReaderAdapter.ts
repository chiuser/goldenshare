import type { NewsReaderViewModel } from "../../../../shared/ui/news-reader/newsReaderTypes";
import { MarketNewsReaderApiError, type NewsReaderItemResponse } from "./marketNewsReaderApi";


export function buildNewsReaderViewModelFromApi(payload: NewsReaderItemResponse): NewsReaderViewModel {
  const payloads = {
    URL: payload.url,
    HTML: payload.html,
    TEXT: payload.content,
  };
  if (!payloads[payload.readerMode] || Object.entries(payloads).some(([mode, value]) => mode !== payload.readerMode && value !== null)) {
    throw new MarketNewsReaderApiError("新闻内容合同无效", "NEWS_READER_CONTRACT_INVALID", 502);
  }
  if (payload.contentSource === "news" && payload.originalUrl !== null) {
    throw new MarketNewsReaderApiError("新闻来源合同无效", "NEWS_READER_CONTRACT_INVALID", 502);
  }
  if (payload.contentSource === "major_news" && (payload.readerMode === "URL" || payload.url !== null)) {
    throw new MarketNewsReaderApiError("新闻通讯正文合同无效", "NEWS_READER_CONTRACT_INVALID", 502);
  }
  return {
    newsId: payload.newsId,
    title: payload.title,
    source: payload.source,
    publishTime: payload.publishTime,
    displayPublishTime: formatPublishTime(payload.publishTime),
    readerMode: payload.readerMode,
    url: payload.url,
    html: payload.html,
    content: payload.content,
  };
}


function formatPublishTime(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    hour12: false,
  }).format(parsed);
}
