import { useCallback, useEffect, useRef, useState } from "react";
import { addWatchlistGroupItem, fetchWatchlistPage, WatchlistApiError } from "../api/watchlistApi";
import type { WatchlistAddResponseDto, WatchlistPageResponseDto, WatchlistSort, WatchlistSortField } from "../api/watchlistApiTypes";
import { buildWatchlistRow } from "./watchlistViewModelAdapter";
import { mutationLocked, watchlistError, type WatchlistMutation, type WatchlistRowViewModel } from "./watchlistTypes";
interface State {
  viewState: "loading" | "ready" | "empty" | "error";
  items: WatchlistRowViewModel[];
  totalCount: number;
  nextCursor: string | null;
  pageContext: WatchlistPageResponseDto["pageContext"] | null;
  dataStatus: WatchlistPageResponseDto["dataStatus"] | null;
  errorMessage: string | null;
  errorCode: string | null;
  loadMoreError: string | null;
  isLoadingMore: boolean;
  scrollResetKey: number;
}
const initial: State = {
  viewState: "loading",
  items: [],
  totalCount: 0,
  nextCursor: null,
  pageContext: null,
  dataStatus: null,
  errorMessage: null,
  errorCode: null,
  loadMoreError: null,
  isLoadingMore: false,
  scrollResetKey: 0
};
type AddAction = {
  groupId: number;
  tsCode: string;
};
export function useWatchlistItemsController(groupId: number | undefined, tradeDate?: string) {
  const [state, setState] = useState(initial);
  const [sorting, setSorting] = useState<{
    groupId?: number;
    sort: WatchlistSort | null;
  }>({
    groupId,
    sort: null
  });
  if (sorting.groupId !== groupId) setSorting({
    groupId,
    sort: null
  });
  const sort = sorting.groupId === groupId ? sorting.sort : null;
  const [mutation, setMutation] = useState<WatchlistMutation<AddAction, WatchlistAddResponseDto>>({
    kind: "idle"
  });
  const write = useRef(mutation);
  write.current = mutation;
  const current = useRef(state);
  current.current = state;
  const mounted = useRef(false);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const context = useRef({
    groupId,
    version: 0
  });
  if (context.current.groupId !== groupId) context.current = {
    groupId,
    version: context.current.version + 1
  };
  useEffect(() => {
    if (write.current.kind !== "idle" && write.current.action.groupId !== groupId) {
      write.current = {
        kind: "idle"
      };
      setMutation(write.current);
    }
  }, [groupId]);
  const update = useCallback((change: (s: State) => State) => {
    if (mounted.current) {
      current.current = change(current.current);
      setState(current.current);
    }
  }, []);
  const reload = useCallback(async () => {
    active.current?.abort();
    const version = ++generation.current;
    const abort = new AbortController();
    active.current = abort;
    update(s => ({
      ...initial,
      scrollResetKey: s.scrollResetKey + 1
    }));
    if (groupId === undefined) {
      active.current = null;
      return false;
    }
    try {
      const response = await fetchWatchlistPage({
        groupId,
        tradeDate,
        ...sort
      }, {
        signal: abort.signal
      });
      if (!mounted.current || abort.signal.aborted || generation.current !== version) return false;
      if (response.dataStatus.status === "ERROR") throw new WatchlistApiError("自选数据暂不可用", "WL_QUERY_FAILED");
      update(s => ({
        ...s,
        items: response.items.map(buildWatchlistRow),
        totalCount: response.totalCount,
        nextCursor: response.nextCursor,
        pageContext: response.pageContext,
        dataStatus: response.dataStatus,
        viewState: response.totalCount ? "ready" : "empty"
      }));
      return true;
    } catch (error) {
      if (!abort.signal.aborted && generation.current === version) update(s => ({
        ...s,
        viewState: "error",
        errorMessage: watchlistError(error).message,
        errorCode: error instanceof WatchlistApiError ? error.code : null
      }));
      return false;
    } finally {
      if (active.current === abort) active.current = null;
    }
  }, [groupId, tradeDate, sort, update]);
  useEffect(() => {
    mounted.current = true;
    void reload();
    return () => {
      mounted.current = false;
      generation.current++;
      active.current?.abort();
    };
  }, [reload]);
  const loadMore = useCallback(async () => {
    if (active.current || !current.current.nextCursor || groupId === undefined || mutationLocked(write.current)) return;
    const abort = new AbortController();
    active.current = abort;
    const version = generation.current;
    update(s => ({
      ...s,
      isLoadingMore: true,
      loadMoreError: null
    }));
    try {
      const response = await fetchWatchlistPage({
        groupId,
        tradeDate,
        ...sort,
        cursor: current.current.nextCursor!
      }, {
        signal: abort.signal
      });
      if (!mounted.current || abort.signal.aborted || version !== generation.current) return;
      if (response.dataStatus.observedTradeDate !== current.current.dataStatus?.observedTradeDate) {
        await reload();
        return;
      }
      if (response.dataStatus.status === "ERROR") throw new WatchlistApiError("自选数据暂不可用", "WL_QUERY_FAILED");
      update(s => {
        const ids = new Set(s.items.map(row => row.membershipId));
        return {
          ...s,
          items: [...s.items, ...response.items.filter(row => !ids.has(row.membershipId)).map(buildWatchlistRow)],
          totalCount: response.totalCount,
          nextCursor: response.nextCursor,
          pageContext: response.pageContext,
          dataStatus: {
            ...response.dataStatus,
            status: s.dataStatus?.status === "PARTIAL" ? "PARTIAL" : response.dataStatus.status
          }
        };
      });
    } catch (error) {
      if (!abort.signal.aborted && version === generation.current) {
        if (error instanceof WatchlistApiError && error.code === "WL_CURSOR_INVALID") await reload();else update(s => ({
          ...s,
          loadMoreError: watchlistError(error).message
        }));
      }
    } finally {
      if (active.current === abort) {
        active.current = null;
        update(s => ({
          ...s,
          isLoadingMore: false
        }));
      }
    }
  }, [groupId, tradeDate, sort, reload, update]);
  async function addToCurrentGroup(tsCode: string) {
    if (groupId === undefined || mutationLocked(write.current)) return null;
    const action = {
      groupId,
      tsCode
    };
    const groupVersion = context.current.version;
    const pending = {
      kind: "pending",
      action
    } as const;
    write.current = pending;
    setMutation(pending);
    const interruptedInitialRead = current.current.viewState === "loading";
    active.current?.abort();
    generation.current++;
    try {
      const result = await addWatchlistGroupItem(groupId, tsCode);
      if (context.current.version !== groupVersion) return null;
      if (mounted.current) {
        const next = {
          kind: "succeeded",
          action,
          result
        } as const;
        write.current = next;
        setMutation(next);
      }
      return result;
    } catch (failure) {
      if (context.current.version !== groupVersion) return null;
      if (mounted.current) {
        const next: WatchlistMutation<AddAction, WatchlistAddResponseDto> = failure instanceof WatchlistApiError && failure.outcome === "UNKNOWN" ? {
          kind: "unknown",
          action
        } : {
          kind: "failed",
          action,
          error: watchlistError(failure)
        };
        write.current = next;
        setMutation(next);
        if (next.kind === "failed" && interruptedInitialRead) void reload();
      }
      throw failure;
    }
  }
  return {
    ...state,
    sort,
    mutation,
    reload,
    loadMore,
    addToCurrentGroup,
    setSort: (sortBy: WatchlistSortField) => setSorting(previous => ({
      groupId,
      sort: {
        sortBy,
        direction: previous.groupId === groupId && previous.sort?.sortBy === sortBy && previous.sort.direction === "desc" ? "asc" : "desc"
      }
    })),
    reconciled: () => {
      if (write.current.kind === "unknown") {
        write.current = {
          kind: "idle"
        };
        setMutation(write.current);
      }
    }
  };
}
