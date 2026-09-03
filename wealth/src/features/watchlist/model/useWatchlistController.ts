import { useCallback, useEffect, useRef, useState } from "react";
import {
  addWatchlistItem,
  fetchWatchlistPage,
  removeWatchlistItem,
  WatchlistApiError,
} from "../api/watchlistApi";
import type {
  WatchlistAddResponseDto,
  WatchlistPageResponseDto,
} from "../api/watchlistApiTypes";
import { buildWatchlistRow } from "./watchlistViewModelAdapter";
import type { WatchlistRowViewModel } from "./watchlistTypes";

interface State {
  viewState: "loading" | "ready" | "empty" | "error";
  pageContext: WatchlistPageResponseDto["pageContext"] | null;
  dataStatus: WatchlistPageResponseDto["dataStatus"] | null;
  items: WatchlistRowViewModel[];
  totalCount: number;
  nextCursor: number | null;
  isLoadingMore: boolean;
  errorMessage: string | null;
  loadMoreError: string | null;
  pendingCodes: string[];
  removeTarget: WatchlistRowViewModel | null;
  memberships: Record<string, boolean>;
  scrollResetKey: number;
  canRetry: boolean;
}
const initial: State = {
  viewState: "loading",
  pageContext: null,
  dataStatus: null,
  items: [],
  totalCount: 0,
  nextCursor: null,
  isLoadingMore: false,
  errorMessage: null,
  loadMoreError: null,
  pendingCodes: [],
  removeTarget: null,
  memberships: {},
  scrollResetKey: 0,
  canRetry: true,
};
const message = (error: unknown) =>
  error instanceof Error ? error.message : "自选操作失败，请重试";

export function useWatchlistController(tradeDate?: string) {
  const [state, setState] = useState<State>(initial);
  const current = useRef(state);
  const mounted = useRef(false);
  const listRequest = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const lastId = useRef<number | undefined>(undefined);
  const mutationQueue = useRef<Promise<unknown>>(Promise.resolve());
  const mutationRequests = useRef(new Set<AbortController>());
  const update = useCallback((change: (previous: State) => State) => {
    if (!mounted.current) return;
    current.current = change(current.current);
    setState(current.current);
  }, []);
  const cancelList = useCallback(() => {
    generation.current += 1;
    listRequest.current?.abort();
    listRequest.current = null;
    update((s) => ({ ...s, isLoadingMore: false }));
  }, [update]);

  const loadInitial = useCallback(async () => {
    cancelList();
    const version = generation.current;
    const controller = new AbortController();
    listRequest.current = controller;
    lastId.current = undefined;
    update((s) => ({
      ...s,
      viewState: "loading",
      items: [],
      nextCursor: null,
      dataStatus: null,
      errorMessage: null,
      loadMoreError: null,
      canRetry: true,
      scrollResetKey: s.scrollResetKey + 1,
    }));
    try {
      const payload = await fetchWatchlistPage(
        { tradeDate },
        { signal: controller.signal },
      );
      if (controller.signal.aborted || version !== generation.current) return;
      if (payload.dataStatus.status === "ERROR")
        throw new Error("自选数据暂不可用，请重试");
      lastId.current = payload.items.at(-1)?.id;
      update((s) => ({
        ...s,
        items: payload.items.map(buildWatchlistRow),
        totalCount: payload.totalCount,
        nextCursor: payload.nextCursor,
        dataStatus: payload.dataStatus,
        pageContext: payload.pageContext,
        viewState: payload.totalCount === 0 ? "empty" : "ready",
      }));
    } catch (error) {
      if (!controller.signal.aborted && version === generation.current)
        update((s) => ({
          ...s,
          viewState: "error",
          errorMessage: message(error),
          canRetry: !(
            error instanceof WatchlistApiError &&
            error.code === "WL_REQUEST_INVALID"
          ),
        }));
    } finally {
      if (listRequest.current === controller) listRequest.current = null;
    }
  }, [cancelList, tradeDate, update]);

  const readMore = useCallback(
    async (afterId: number) => {
      if (listRequest.current || !mounted.current) return;
      const controller = new AbortController();
      const version = generation.current;
      listRequest.current = controller;
      update((s) => ({ ...s, isLoadingMore: true, loadMoreError: null }));
      try {
        const payload = await fetchWatchlistPage(
          { tradeDate, afterId },
          { signal: controller.signal },
        );
        if (controller.signal.aborted || version !== generation.current) return;
        if (
          payload.dataStatus.observedTradeDate !==
          current.current.dataStatus?.observedTradeDate
        ) {
          listRequest.current = null;
          await loadInitial();
          return;
        }
        if (payload.dataStatus.status === "ERROR")
          throw new Error("自选数据暂不可用，请重试");
        lastId.current = payload.items.at(-1)?.id ?? lastId.current;
        update((s) => {
          const existing = new Set(s.items.map((row) => row.tsCode));
          return {
            ...s,
            items: [
              ...s.items,
              ...payload.items
                .filter((item) => !existing.has(item.stock.tsCode))
                .map(buildWatchlistRow),
            ],
            totalCount: payload.totalCount,
            nextCursor: payload.nextCursor,
            pageContext: payload.pageContext,
            viewState: payload.totalCount === 0 ? "empty" : "ready",
            dataStatus: {
              ...payload.dataStatus,
              status:
                s.dataStatus?.status === "PARTIAL"
                  ? "PARTIAL"
                  : payload.dataStatus.status,
            },
          };
        });
      } catch (error) {
        if (!controller.signal.aborted && version === generation.current)
          update((s) => ({ ...s, loadMoreError: message(error) }));
      } finally {
        if (listRequest.current === controller) {
          listRequest.current = null;
          update((s) => ({ ...s, isLoadingMore: false }));
        }
      }
    },
    [loadInitial, tradeDate, update],
  );

  useEffect(() => {
    mounted.current = true;
    void loadInitial();
    return () => {
      mounted.current = false;
      generation.current += 1;
      listRequest.current?.abort();
      mutationRequests.current.forEach((controller) => controller.abort());
    };
  }, [loadInitial]);

  function queueMutation<T>(
    tsCode: string,
    operation: (signal: AbortSignal) => Promise<T>,
  ): Promise<T> {
    if (current.current.pendingCodes.includes(tsCode))
      return Promise.reject(new Error("该股票正在处理中"));
    update((s) => ({
      ...s,
      pendingCodes: [...s.pendingCodes, tsCode],
      errorMessage: null,
    }));
    const task = mutationQueue.current
      .catch(() => undefined)
      .then(async () => {
        if (!mounted.current)
          throw new DOMException("页面已关闭", "AbortError");
        const interruptedInitialLoad = current.current.viewState === "loading";
        cancelList();
        const controller = new AbortController();
        mutationRequests.current.add(controller);
        try {
          return await operation(controller.signal);
        } finally {
          mutationRequests.current.delete(controller);
          if (
            interruptedInitialLoad &&
            mounted.current &&
            current.current.viewState === "loading"
          )
            await loadInitial();
        }
      })
      .finally(() =>
        update((s) => ({
          ...s,
          pendingCodes: s.pendingCodes.filter((code) => code !== tsCode),
        })),
      );
    mutationQueue.current = task;
    return task;
  }

  async function appendAddedItem(
    tsCode: string,
  ): Promise<WatchlistAddResponseDto> {
    return queueMutation(tsCode, async (signal) => {
      const result = await addWatchlistItem(tsCode, { signal });
      if (!mounted.current || signal.aborted) return result;
      const alreadyLoaded = current.current.items.some(
        (row) => row.tsCode === result.tsCode,
      );
      const hasMore = current.current.nextCursor !== null;
      update((s) => ({
        ...s,
        totalCount: result.totalCount,
        memberships: { ...s.memberships, [result.tsCode]: true },
      }));
      if (!alreadyLoaded && !hasMore) {
        if (lastId.current === undefined) await loadInitial();
        else await readMore(lastId.current);
      }
      return result;
    });
  }

  async function confirmRemove() {
    const target = current.current.removeTarget;
    if (!target || current.current.pendingCodes.includes(target.tsCode)) return;
    try {
      await queueMutation(target.tsCode, async (signal) => {
        const result = await removeWatchlistItem(target.tsCode, { signal });
        if (!mounted.current || signal.aborted) return;
        update((s) => ({
          ...s,
          items: s.items.filter((row) => row.tsCode !== result.tsCode),
          totalCount: result.totalCount,
          memberships: { ...s.memberships, [result.tsCode]: false },
          removeTarget: null,
          viewState: result.totalCount === 0 ? "empty" : "ready",
          nextCursor: result.totalCount === 0 ? null : s.nextCursor,
        }));
        if (result.totalCount > 0 && current.current.items.length === 0)
          await loadInitial();
      });
    } catch (error) {
      update((s) => ({ ...s, errorMessage: message(error) }));
    }
  }

  return {
    ...state,
    appendAddedItem,
    confirmRemove,
    retry: loadInitial,
    loadMore: () => {
      if (
        current.current.nextCursor !== null &&
        current.current.pendingCodes.length === 0
      )
        void readMore(current.current.nextCursor);
    },
    retryMore: () => {
      if (lastId.current !== undefined) void readMore(lastId.current);
    },
    requestRemove: (row: WatchlistRowViewModel) =>
      update((s) => ({ ...s, removeTarget: row, errorMessage: null })),
    cancelRemove: () =>
      update((s) =>
        s.removeTarget && s.pendingCodes.includes(s.removeTarget.tsCode)
          ? s
          : { ...s, removeTarget: null, errorMessage: null },
      ),
  };
}
