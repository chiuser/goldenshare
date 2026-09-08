import { useCallback, useEffect, useRef, useState } from "react";
import { searchWatchlistCandidates, WatchlistApiError } from "../api/watchlistApi";
import type { WatchlistCandidateDto, WatchlistSearchResponseDto } from "../api/watchlistApiTypes";
export const WATCHLIST_SEARCH_DEBOUNCE_MS = 500;
export function useWatchlistSearchController(groupId: number, open: boolean) {
  const [keyword, setKeyword] = useState("");
  const [items, setItems] = useState<WatchlistCandidateDto[]>([]);
  const [status, setStatus] = useState<"idle" | "debouncing" | "loading" | "ready" | "empty" | "error">("idle");
  const [error, setError] = useState("");
  const [canRetry, setCanRetry] = useState(true);
  const [composing, setComposing] = useState(false);
  const version = useRef(0);
  const active = useRef<AbortController | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const cancel = useCallback(() => {
    version.current++;
    active.current?.abort();
    window.clearTimeout(timer.current);
  }, []);
  const refresh = useCallback(async (): Promise<WatchlistSearchResponseDto | null> => {
    cancel();
    if (!open || !keyword.trim() || composing) return null;
    const requestVersion = version.current;
    const controller = new AbortController();
    active.current = controller;
    setStatus("loading");
    setError("");
    setCanRetry(true);
    try {
      const response = await searchWatchlistCandidates({
        groupId,
        keyword: keyword.trim()
      }, {
        signal: controller.signal
      });
      if (controller.signal.aborted || version.current !== requestVersion) return null;
      if (response.groupId !== groupId) throw new WatchlistApiError("搜索分组数据异常", "WL_QUERY_FAILED");
      setItems(response.items);
      setStatus(response.items.length ? "ready" : "empty");
      return response;
    } catch (failure) {
      if (controller.signal.aborted || version.current !== requestVersion) return null;
      setError(failure instanceof Error ? failure.message : "搜索失败，请重试");
      setCanRetry(!(failure instanceof WatchlistApiError && failure.code === "WL_REQUEST_INVALID"));
      setStatus("error");
      return null;
    }
  }, [cancel, composing, groupId, keyword, open]);
  useEffect(() => {
    cancel();
    setItems([]);
    setError("");
    setCanRetry(true);
    if (!open || !keyword.trim() || composing) {
      setStatus("idle");
      if (!open) {
        setKeyword("");
        setComposing(false);
      }
    } else {
      setStatus("debouncing");
      timer.current = window.setTimeout(() => void refresh(), WATCHLIST_SEARCH_DEBOUNCE_MS);
    }
    return cancel;
  }, [cancel, refresh, composing, groupId, keyword, open]);
  return {
    keyword,
    items,
    status,
    error,
    canRetry,
    refresh,
    setComposing,
    setKeyword: (value: string) => {
      cancel();
      setKeyword(value);
      setItems([]);
      setStatus(value.trim() ? "debouncing" : "idle");
    },
    retry: () => void refresh()
  };
}
