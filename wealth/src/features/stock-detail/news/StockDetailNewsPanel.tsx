import { useEffect, useRef, useState } from "react";

import {
  fetchStockDetailNews,
  StockDetailNewsApiError,
} from "./api/stockDetailNewsApiClient";
import { adaptStockDetailNews, type StockDetailNewsItemViewModel } from "./api/stockDetailNewsViewModelAdapter";
import "./stock-detail-news.css";

type NewsPanelState = "idle" | "loading" | "ready-empty" | "ready-items" | "error";

interface StockDetailNewsPanelProps {
  tsCode: string;
  tradeDate: string;
  active: boolean;
}

function newsWindowEnd(tradeDate: string): string {
  const nextDay = new Date(`${tradeDate}T00:00:00Z`);
  nextDay.setUTCDate(nextDay.getUTCDate() + 1);
  return `${nextDay.toISOString().slice(0, 10)}T00:00:00+08:00`;
}

export function StockDetailNewsPanel({ tsCode, tradeDate, active }: StockDetailNewsPanelProps) {
  const key = `${tsCode}|${tradeDate}`;
  const [state, setState] = useState<NewsPanelState>("idle");
  const [items, setItems] = useState<StockDetailNewsItemViewModel[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const loadedKeyRef = useRef<string | null>(null);
  const requestedKeyRef = useRef<string | null>(null);

  useEffect(() => {
    loadedKeyRef.current = null;
    requestedKeyRef.current = null;
    setState("idle");
    setItems([]);
    setErrorMessage("");
  }, [key]);

  useEffect(() => {
    if (!active || loadedKeyRef.current === key) return;

    const controller = new AbortController();
    requestedKeyRef.current = key;
    setState("loading");
    setItems([]);
    setErrorMessage("");

    void fetchStockDetailNews(
      { tsCode, endAt: newsWindowEnd(tradeDate), limit: 50 }, { signal: controller.signal },
    )
      .then((response) => {
        if (controller.signal.aborted) return;
        loadedKeyRef.current = key;
        const nextItems = adaptStockDetailNews(response);
        setItems(nextItems);
        setState(nextItems.length > 0 ? "ready-items" : "ready-empty");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setErrorMessage(error instanceof StockDetailNewsApiError || error instanceof Error ? error.message : "新闻加载失败");
        setState("error");
      });

    return () => controller.abort();
  }, [active, key, tsCode, tradeDate]);

  const currentState: NewsPanelState = requestedKeyRef.current === key ? state : active ? "loading" : "idle";
  const currentItems = loadedKeyRef.current === key ? items : [];

  return (
    <section className="stock-detail-news-panel" data-state={currentState} aria-label="个股新闻">
      {currentState === "idle" && <div className="stock-detail-news-state">点击“新闻”加载相关新闻</div>}
      {currentState === "loading" && <div className="stock-detail-news-state">新闻加载中</div>}
      {currentState === "ready-empty" && <div className="stock-detail-news-state">暂无相关新闻</div>}
      {currentState === "error" && <div className="stock-detail-news-state">{errorMessage || "新闻加载失败"}</div>}
      {currentState === "ready-items" && (
        <div className="stock-detail-news-list" role="list">
          {currentItems.map((item) => (
            <div className="stock-detail-news-item" role="listitem" key={item.newsId}>
              <span className="stock-detail-news-title">{item.title}</span>
              <time className="stock-detail-news-date" dateTime={item.publishTime}>{item.displayDate}</time>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
