import { useEffect, useRef, useState } from "react";
import {
  searchWatchlistCandidates,
  WatchlistApiError,
} from "../api/watchlistApi";
import type { WatchlistCandidateDto } from "../api/watchlistApiTypes";

export const WATCHLIST_SEARCH_DEBOUNCE_MS = 500;
export function useWatchlistSearchController(open: boolean) {
  const [keyword, setKeyword] = useState("");
  const [items, setItems] = useState<WatchlistCandidateDto[]>([]);
  const [status, setStatus] = useState<
    "idle" | "debouncing" | "loading" | "ready" | "empty" | "error"
  >("idle");
  const [error, setError] = useState("");
  const [canRetry, setCanRetry] = useState(true);
  const [retryKey, setRetryKey] = useState(0);
  const version = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const [composing, setComposing] = useState(false);

  useEffect(() => {
    const requestVersion = ++version.current;
    const controller = new AbortController();
    activeRequest.current = controller;
    setItems([]);
    setError("");
    setCanRetry(true);
    if (!open || !keyword.trim() || composing) {
      setStatus("idle");
      if (!open) {
        setKeyword("");
        setComposing(false);
      }
      return () => controller.abort();
    }
    setStatus("debouncing");
    const timer = window.setTimeout(async () => {
      setStatus("loading");
      try {
        const response = await searchWatchlistCandidates(
          { keyword: keyword.trim() },
          { signal: controller.signal },
        );
        if (controller.signal.aborted || version.current !== requestVersion)
          return;
        setItems(response.items);
        setStatus(response.items.length ? "ready" : "empty");
      } catch (failure) {
        if (controller.signal.aborted || version.current !== requestVersion)
          return;
        setError(
          failure instanceof Error ? failure.message : "搜索失败，请重试",
        );
        setCanRetry(
          !(
            failure instanceof WatchlistApiError &&
            failure.code === "WL_REQUEST_INVALID"
          ),
        );
        setStatus("error");
      }
    }, WATCHLIST_SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [composing, keyword, open, retryKey]);

  return {
    keyword,
    items,
    status,
    error,
    canRetry,
    setComposing,
    setKeyword: (value: string) => {
      version.current += 1;
      activeRequest.current?.abort();
      setKeyword(value);
      setItems([]);
      setStatus(value.trim() ? "debouncing" : "idle");
    },
    retry: () => setRetryKey((key) => key + 1),
  };
}
