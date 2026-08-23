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
  active: boolean;
}

export function StockDetailNewsPanel({ tsCode, active }: StockDetailNewsPanelProps) {
  const [state, setState] = useState<NewsPanelState>("idle");
  const [items, setItems] = useState<StockDetailNewsItemViewModel[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const loadedTsCodeRef = useRef<string | null>(null);
  const requestedTsCodeRef = useRef<string | null>(null);

  useEffect(() => {
    loadedTsCodeRef.current = null;
    requestedTsCodeRef.current = null;
    setState("idle");
    setItems([]);
    setErrorMessage("");
  }, [tsCode]);

  useEffect(() => {
    if (!active || loadedTsCodeRef.current === tsCode) return;

    const controller = new AbortController();
    requestedTsCodeRef.current = tsCode;
    setState("loading");
    setItems([]);
    setErrorMessage("");

    void fetchStockDetailNews({ tsCode, limit: 50 }, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        loadedTsCodeRef.current = tsCode;
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
  }, [active, tsCode]);

  const currentState: NewsPanelState = requestedTsCodeRef.current === tsCode ? state : active ? "loading" : "idle";
  const currentItems = loadedTsCodeRef.current === tsCode ? items : [];

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
