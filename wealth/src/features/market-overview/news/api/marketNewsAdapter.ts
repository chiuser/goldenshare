import type { MarketNewsBriefsResponse, NewsListPanelResponse, StockNewsResponse } from "./marketNewsApi";

export interface MarketNewsViewItem {
  newsId: string;
  publishTime: string;
  displayTime: string;
  title: string;
  clickable: false;
}

export interface MarketNewsPanelViewModel {
  title: "新闻速览" | "个股新闻";
  visibleItemCount: number;
  updatedAt: string;
  items: MarketNewsViewItem[];
  statusLabel: string;
  statusTone: "ready" | "delayed";
}

export function buildNewsBriefsViewModelFromApi(payload: MarketNewsBriefsResponse): MarketNewsPanelViewModel {
  return buildPanelViewModel(payload.newsBriefs, "新闻速览", payload.pageStatus.displayText, payload.pageStatus.status);
}

export function buildStockNewsViewModelFromApi(payload: StockNewsResponse): MarketNewsPanelViewModel {
  return buildPanelViewModel(payload.stockNews, "个股新闻", payload.pageStatus.displayText, payload.pageStatus.status);
}

function buildPanelViewModel(
  panel: NewsListPanelResponse,
  title: "新闻速览" | "个股新闻",
  statusLabel: string,
  status: string,
): MarketNewsPanelViewModel {
  return {
    title,
    visibleItemCount: panel.visibleItemCount,
    updatedAt: panel.updatedAt,
    items: panel.items.map((item) => ({
      newsId: item.newsId,
      publishTime: item.publishTime,
      displayTime: item.displayTime,
      title: item.title,
      clickable: false,
    })),
    statusLabel,
    statusTone: status === "READY" ? "ready" : "delayed",
  };
}
