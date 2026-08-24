import type { NewsReaderMode } from "../../../../shared/ui/news-reader/newsReaderTypes";
import type {
  MarketNewsBriefsResponse,
  NewsCommunicationsResponse,
  NewsContentSource,
  NewsListPanelResponse,
} from "./marketNewsApi";

export interface MarketNewsViewItem {
  newsId: string;
  contentSource: NewsContentSource;
  publishTime: string;
  displayTime: string;
  title: string;
  readerMode: NewsReaderMode;
  clickable: true;
}

export interface MarketNewsPanelViewModel {
  title: "新闻速览" | "新闻通讯";
  visibleItemCount: number;
  updatedAt: string;
  items: MarketNewsViewItem[];
  statusLabel: string;
  statusTone: "ready" | "delayed";
}

export function buildNewsBriefsViewModelFromApi(payload: MarketNewsBriefsResponse): MarketNewsPanelViewModel {
  return buildPanelViewModel(payload.newsBriefs, "新闻速览", payload.pageStatus.displayText, payload.pageStatus.status);
}

export function buildNewsCommunicationsViewModelFromApi(
  payload: NewsCommunicationsResponse,
): MarketNewsPanelViewModel {
  return buildPanelViewModel(
    payload.newsCommunications,
    "新闻通讯",
    payload.pageStatus.displayText,
    payload.pageStatus.status,
  );
}

function buildPanelViewModel(
  panel: NewsListPanelResponse,
  title: "新闻速览" | "新闻通讯",
  statusLabel: string,
  status: string,
): MarketNewsPanelViewModel {
  return {
    title,
    visibleItemCount: panel.visibleItemCount,
    updatedAt: panel.updatedAt,
    items: panel.items.map((item) => ({
      newsId: item.newsId,
      contentSource: item.contentSource,
      publishTime: item.publishTime,
      displayTime: item.displayTime,
      title: item.title,
      readerMode: item.readerMode,
      clickable: true,
    })),
    statusLabel,
    statusTone: status === "READY" ? "ready" : "delayed",
  };
}
