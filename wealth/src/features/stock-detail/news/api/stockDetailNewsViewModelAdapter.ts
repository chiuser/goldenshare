import type { StockDetailNewsApiItem, StockDetailNewsApiResponse } from "./stockDetailNewsApiTypes";

export interface StockDetailNewsItemViewModel {
  newsId: string;
  title: string;
  publishTime: string;
  displayDate: string;
}

export function adaptStockDetailNews(response: StockDetailNewsApiResponse, now = new Date()): StockDetailNewsItemViewModel[] {
  return response.items.map((item) => adaptStockDetailNewsItem(item, now));
}

export function adaptStockDetailNewsItem(item: StockDetailNewsApiItem, now = new Date()): StockDetailNewsItemViewModel {
  return {
    newsId: item.newsId,
    title: item.title,
    publishTime: item.publishTime,
    displayDate: formatNewsDate(item.publishTime, now),
  };
}

export function formatNewsDate(publishTime: string, now = new Date()): string {
  const publishParts = dateParts(publishTime);
  const currentYear = dateParts(now.toISOString()).year;
  if (publishParts.year === currentYear) return `${publishParts.month}-${publishParts.day}`;
  return `${publishParts.year}-${publishParts.month}-${publishParts.day}`;
}

function dateParts(value: string): { year: string; month: string; day: string } {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date(value));
  return {
    year: parts.find((part) => part.type === "year")?.value ?? "",
    month: parts.find((part) => part.type === "month")?.value ?? "",
    day: parts.find((part) => part.type === "day")?.value ?? "",
  };
}
