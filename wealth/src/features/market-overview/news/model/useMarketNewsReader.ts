import { useCallback, useEffect, useRef, useState } from "react";

import type { NewsReaderDialogState } from "../../../../shared/ui/news-reader/newsReaderTypes";
import type { MarketNewsViewItem } from "../api/marketNewsAdapter";
import { buildNewsReaderViewModelFromApi } from "../api/marketNewsReaderAdapter";
import {
  fetchMarketNewsReaderItem,
  MarketNewsReaderApiError,
} from "../api/marketNewsReaderApi";


const NEWS_READER_FETCH_TIMEOUT_MS = 5_000;


export interface MarketNewsReaderIdentity {
  contentSource: MarketNewsViewItem["contentSource"];
  newsId: string;
}


export interface MarketNewsReaderController {
  state: NewsReaderDialogState;
  open(item: MarketNewsViewItem, trigger: HTMLElement): void;
  close(): void;
  retry(): void;
}


export function useMarketNewsReader(): MarketNewsReaderController {
  const [state, setState] = useState<NewsReaderDialogState>({ status: "closed" });
  const requestSequenceRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const selectedItemRef = useRef<MarketNewsViewItem | null>(null);
  const triggerRef = useRef<HTMLElement | null>(null);
  const triggerIdentityRef = useRef<MarketNewsReaderIdentity | null>(null);

  const load = useCallback((item: MarketNewsViewItem) => {
    abortControllerRef.current?.abort();
    const requestId = ++requestSequenceRef.current;
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    let timedOut = false;
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      abortController.abort();
    }, NEWS_READER_FETCH_TIMEOUT_MS);

    setState({
      status: "loading",
      newsId: item.newsId,
      title: item.title,
      publishTime: item.publishTime,
      readerMode: item.readerMode,
      requestId,
    });

    const identity = { contentSource: item.contentSource, newsId: item.newsId } satisfies MarketNewsReaderIdentity;
    fetchMarketNewsReaderItem(identity.contentSource, identity.newsId, { signal: abortController.signal })
      .then((payload) => {
        if (abortController.signal.aborted || requestSequenceRef.current !== requestId) return;
        if (payload.newsId !== identity.newsId || payload.contentSource !== identity.contentSource) {
          throw new MarketNewsReaderApiError("新闻身份与请求不一致", "NEWS_READER_CONTRACT_INVALID", 502);
        }
        setState({ status: "ready", requestId, item: buildNewsReaderViewModelFromApi(payload) });
      })
      .catch((error: unknown) => {
        if (requestSequenceRef.current !== requestId) return;
        if (abortController.signal.aborted && !timedOut) return;
        const readerError = error instanceof MarketNewsReaderApiError ? error : null;
        if (readerError?.status === 404 || readerError?.code === "NEWS_READER_NOT_FOUND") {
          setState({
            status: "empty",
            newsId: item.newsId,
            title: item.title,
            publishTime: item.publishTime,
            message: readerError.message,
          });
          return;
        }
        const retryable =
          timedOut ||
          !readerError ||
          (readerError.status >= 500 && readerError.code !== "NEWS_READER_CONTRACT_INVALID");
        setState({
          status: "error",
          newsId: item.newsId,
          title: item.title,
          publishTime: item.publishTime,
          message: timedOut ? "新闻内容请求超时，请稍后重试。" : error instanceof Error ? error.message : "新闻内容加载失败。",
          retryable,
        });
      })
      .finally(() => {
        window.clearTimeout(timeoutId);
        if (abortControllerRef.current === abortController) abortControllerRef.current = null;
      });
  }, []);

  const open = useCallback(
    (item: MarketNewsViewItem, trigger: HTMLElement) => {
      selectedItemRef.current = item;
      triggerRef.current = trigger;
      triggerIdentityRef.current = { contentSource: item.contentSource, newsId: item.newsId };
      load(item);
    },
    [load],
  );

  const close = useCallback(() => {
    abortControllerRef.current?.abort();
    abortControllerRef.current = null;
    requestSequenceRef.current += 1;
    selectedItemRef.current = null;
    setState({ status: "closed" });

    const trigger = triggerRef.current;
    const identity = triggerIdentityRef.current;
    triggerRef.current = null;
    triggerIdentityRef.current = null;
    window.requestAnimationFrame(() => {
      if (trigger?.isConnected) {
        trigger.focus({ preventScroll: true });
        return;
      }
      if (!identity) return;
      const escapedSource = escapeAttributeValue(identity.contentSource);
      const escapedNewsId = escapeAttributeValue(identity.newsId);
      const replacement = document.querySelector<HTMLElement>(
        `[data-news-reader-trigger][data-news-source="${escapedSource}"][data-news-id="${escapedNewsId}"]`,
      );
      replacement?.focus({ preventScroll: true });
    });
  }, []);

  const retry = useCallback(() => {
    const item = selectedItemRef.current;
    if (item) load(item);
  }, [load]);

  useEffect(
    () => () => {
      abortControllerRef.current?.abort();
      requestSequenceRef.current += 1;
    },
    [],
  );

  return { state, open, close, retry };
}


function escapeAttributeValue(value: string): string {
  return window.CSS?.escape ? window.CSS.escape(value) : value.replace(/["\\]/g, "\\$&");
}
