import type { CSSProperties } from "react";

import { SkeletonBlock } from "../../../shared/ui/SkeletonBlock";
import type { MarketNewsPanelViewModel } from "./api/marketNewsAdapter";

interface MarketNewsPanelProps {
  title: "新闻速览" | "个股新闻";
  viewState: "loading" | "ready" | "error";
  panel?: MarketNewsPanelViewModel | null;
  errorMessage?: string;
  onItemOpen?: (item: MarketNewsPanelViewModel["items"][number], trigger: HTMLButtonElement) => void;
}

export function MarketNewsPanel({ title, viewState, panel, errorMessage, onItemOpen }: MarketNewsPanelProps) {
  const visibleItemCount = panel?.visibleItemCount ?? 10;
  const items = panel?.items ?? [];
  const trackKey = `${panel?.updatedAt ?? "pending"}-${items[0]?.newsId ?? "empty"}-${items.length}`;

  return (
    <section
      className="market-news-panel"
      aria-label={title}
      style={{ "--news-list-height": `${visibleItemCount * 22}px` } as CSSProperties}
    >
      <div className="market-news-head">
        <div className="market-news-title">{title}</div>
        <span className="market-news-count">{visibleItemCount} 条可见</span>
      </div>
      <div className="market-news-viewport" aria-label={`${title}列表`}>
        {viewState === "loading" ? <SkeletonBlock /> : null}
        {viewState === "error" ? (
          <div className="state-block error-box market-news-state">
            <strong>error</strong>
            <br />
            <span>{errorMessage ?? "请求超时，请稍后重试。"}</span>
          </div>
        ) : null}
        {viewState === "ready" && items.length === 0 ? (
          <div className="state-block empty-box market-news-state">
            <span>—</span>
            <span>当前交易日暂无可展示新闻。</span>
          </div>
        ) : null}
        {viewState === "ready" && items.length > 0 ? (
          <NewsTickerList key={trackKey} items={items} visibleItemCount={visibleItemCount} onItemOpen={onItemOpen} />
        ) : null}
      </div>
    </section>
  );
}

interface NewsTickerListProps {
  items: MarketNewsPanelViewModel["items"];
  visibleItemCount: number;
  onItemOpen?: MarketNewsPanelProps["onItemOpen"];
}

function NewsTickerList({ items, visibleItemCount, onItemOpen }: NewsTickerListProps) {
  const shouldScroll = items.length > visibleItemCount;
  const renderItems = shouldScroll ? [...items, ...items] : items;
  const scrollDurationSeconds = Math.max(40, items.length * 2);

  return (
    <div
      className={shouldScroll ? "market-news-track scrolling" : "market-news-track"}
      style={{ "--news-scroll-duration": `${scrollDurationSeconds}s` } as CSSProperties}
    >
      {renderItems.map((item, index) => (
        <button
          type="button"
          className="market-news-item"
          data-news-reader-trigger
          data-news-id={item.newsId}
          key={`${item.newsId}-${index}`}
          title={`${item.displayTime}｜${item.title}`}
          aria-haspopup="dialog"
          onClick={(event) => onItemOpen?.(item, event.currentTarget)}
        >
          <span className="market-news-time">{item.displayTime}</span>
          <span className="market-news-text">{item.title}</span>
        </button>
      ))}
    </div>
  );
}
