import { useEffect, useRef, useState } from "react";
import {
  addWatchlistItem,
  fetchWatchlistMembership,
} from "../api/watchlistApi";

export type StockWatchlistState = "loading" | "available" | "added" | "error";
export function useStockWatchlist(tsCode: string, enabled: boolean) {
  const [state, setState] = useState<{
    code: string;
    status: StockWatchlistState;
    error: string;
  }>({ code: tsCode, status: "loading", error: "" });
  const request = useRef<AbortController | null>(null);
  const adding = useRef(false);
  useEffect(() => {
    const controller = new AbortController();
    request.current = controller;
    adding.current = false;
    setState({ code: tsCode, status: "loading", error: "" });
    if (enabled)
      void fetchWatchlistMembership(tsCode, { signal: controller.signal })
        .then((result) => {
          if (!controller.signal.aborted)
            setState({
              code: tsCode,
              status: result.isAdded ? "added" : "available",
              error: "",
            });
        })
        .catch((error) => {
          if (!controller.signal.aborted)
            setState({
              code: tsCode,
              status: "error",
              error:
                error instanceof Error
                  ? error.message
                  : "读取自选状态失败，可点击重试",
            });
        });
    return () => {
      controller.abort();
      request.current?.abort();
    };
  }, [tsCode, enabled]);
  async function add() {
    if (
      !enabled ||
      adding.current ||
      state.code !== tsCode ||
      state.status === "added"
    )
      return;
    adding.current = true;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setState({ code: tsCode, status: "loading", error: "" });
    try {
      await addWatchlistItem(tsCode, { signal: controller.signal });
      if (!controller.signal.aborted)
        setState({ code: tsCode, status: "added", error: "" });
    } catch (error) {
      if (!controller.signal.aborted)
        setState({
          code: tsCode,
          status: "error",
          error: error instanceof Error ? error.message : "添加失败，请重试",
        });
    } finally {
      if (request.current === controller) adding.current = false;
    }
  }
  return {
    status:
      state.code === tsCode && enabled
        ? state.status
        : ("loading" as StockWatchlistState),
    error: state.code === tsCode && enabled ? state.error : "",
    add,
  };
}
