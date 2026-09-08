import { useCallback, useEffect, useRef, useState } from "react";
import { fetchStockWatchlistGroups, replaceStockWatchlistGroups, WatchlistApiError } from "../api/watchlistApi";
import type { WatchlistStockGroupDto, WatchlistStockGroupsReplaceResponseDto } from "../api/watchlistApiTypes";
import { mutationLocked, watchlistError, type WatchlistMutation } from "./watchlistTypes";
type Action = {
  tsCode: string;
  groupIds: number[];
};
export function useStockWatchlistGroups(tsCode: string, enabled: boolean) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [groups, setGroups] = useState<WatchlistStockGroupDto[]>([]);
  const [committedIds, setCommittedIds] = useState<Set<number>>(new Set());
  const [draftIds, setDraftIds] = useState<Set<number>>(new Set());
  const [error, setError] = useState("");
  const [mutation, setMutation] = useState<WatchlistMutation<Action, WatchlistStockGroupsReplaceResponseDto>>({
    kind: "idle"
  });
  const write = useRef(mutation);
  write.current = mutation;
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const mounted = useRef(false);
  const identity = useRef(0);
  const refresh = useCallback(async () => {
    request.current?.abort();
    const abort = new AbortController();
    request.current = abort;
    const version = ++generation.current;
    setStatus("loading");
    setError("");
    try {
      const result = await fetchStockWatchlistGroups(tsCode, {
        signal: abort.signal
      });
      if (!mounted.current || abort.signal.aborted || version !== generation.current) return;
      const selected = new Set(result.groups.filter(g => g.selected).map(g => g.groupId));
      setGroups(result.groups);
      setCommittedIds(selected);
      setDraftIds(new Set(selected));
      setStatus("ready");
      if (write.current.kind === "unknown") {
        write.current = {
          kind: "idle"
        };
        setMutation(write.current);
      }
    } catch (failure) {
      if (mounted.current && !abort.signal.aborted && version === generation.current) {
        setError(watchlistError(failure).message);
        setStatus("error");
      }
    }
  }, [tsCode]);
  useEffect(() => {
    mounted.current = true;
    setOpen(false);
    setGroups([]);
    setCommittedIds(new Set());
    setDraftIds(new Set());
    write.current = {
      kind: "idle"
    };
    setMutation(write.current);
    if (enabled) void refresh();else setStatus("idle");
    return () => {
      mounted.current = false;
      identity.current++;
      generation.current++;
      request.current?.abort();
    };
  }, [enabled, refresh]);
  const cancel = () => {
    if (mutationLocked(write.current)) return;
    request.current?.abort();
    generation.current++;
    setOpen(false);
    setDraftIds(new Set(committedIds));
    setError("");
    setStatus("ready");
  };
  async function confirm() {
    if (!enabled || !open || status !== "ready" || !draftIds.size || mutationLocked(write.current)) return;
    const action = {
      tsCode,
      groupIds: [...draftIds]
    };
    const stockVersion = identity.current;
    const pending = {
      kind: "pending",
      action
    } as const;
    write.current = pending;
    setMutation(pending);
    try {
      const result = await replaceStockWatchlistGroups(tsCode, action.groupIds);
      if (!mounted.current || identity.current !== stockVersion) return;
      const next = {
        kind: "succeeded",
        action,
        result
      } as const;
      write.current = next;
      setMutation(next);
      setCommittedIds(new Set(result.groupIds));
      setDraftIds(new Set(result.groupIds));
      setOpen(false);
    } catch (failure) {
      if (!mounted.current || identity.current !== stockVersion) return;
      if (failure instanceof WatchlistApiError && failure.outcome === "UNKNOWN") {
        write.current = {
          kind: "unknown",
          action
        };
        setMutation(write.current);
        await refresh();
      } else {
        write.current = {
          kind: "failed",
          action,
          error: watchlistError(failure)
        };
        setMutation(write.current);
      }
    }
  }
  return {
    open,
    status,
    groups,
    committedIds,
    draftIds,
    error,
    mutation,
    isAdded: committedIds.size > 0,
    saving: mutation.kind === "pending",
    confirm,
    cancel,
    retry: refresh,
    show: () => {
      if (enabled && !mutationLocked(write.current)) {
        write.current = {
          kind: "idle"
        };
        setMutation(write.current);
        setOpen(true);
        void refresh();
      }
    },
    toggle: (id: number) => {
      if (status !== "ready" || mutationLocked(write.current) || !groups.some(g => g.groupId === id)) return;
      setDraftIds(previous => {
        const next = new Set(previous);
        if (next.has(id)) next.delete(id);else next.add(id);
        return next;
      });
    }
  };
}
