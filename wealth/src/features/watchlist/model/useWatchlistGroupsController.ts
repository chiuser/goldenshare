import { useCallback, useEffect, useRef, useState } from "react";
import { changeWatchlistGroupColor, createWatchlistGroup, deleteWatchlistGroup, fetchWatchlistGroups, WatchlistApiError } from "../api/watchlistApi";
import type { WatchlistGroupDeleteResponseDto, WatchlistGroupDto, WatchlistGroupsResponseDto } from "../api/watchlistApiTypes";
import { mutationLocked, watchlistError, type WatchlistMutation } from "./watchlistTypes";
type Action = {
  type: "create";
  name: string;
  color: string;
} | {
  type: "color";
  groupId: number;
  color: string;
} | {
  type: "delete";
  groupId: number;
};
type Result = WatchlistGroupDto | WatchlistGroupDeleteResponseDto;
type State = {
  kind: "loading";
} | ({
  kind: "ready";
  currentGroupId: number;
} & WatchlistGroupsResponseDto) | {
  kind: "error";
  message: string;
  canRetry: boolean;
};
export function useWatchlistGroupsController() {
  const [state, setState] = useState<State>({
    kind: "loading"
  });
  const [mutation, setMutation] = useState<WatchlistMutation<Action, Result>>({
    kind: "idle"
  });
  const current = useRef(state);
  current.current = state;
  const write = useRef(mutation);
  write.current = mutation;
  const mounted = useRef(false);
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const selected = useRef<number | undefined>(undefined);
  const activeGroup = useRef<number | undefined>(undefined);
  const refresh = useCallback(async (targetId?: number) => {
    if (targetId !== undefined) selected.current = targetId;
    request.current?.abort();
    const abort = new AbortController();
    request.current = abort;
    const version = ++generation.current;
    if (current.current.kind !== "ready") setState({
      kind: "loading"
    });
    try {
      const result = await fetchWatchlistGroups({
        signal: abort.signal
      });
      if (abort.signal.aborted || version !== generation.current || !mounted.current) return null;
      const defaults = result.groups.filter(g => g.isDefault);
      if (defaults.length !== 1) throw new WatchlistApiError("默认分组数据异常，请重试读取", "WL_QUERY_FAILED");
      const currentGroupId = result.groups.find(g => g.id === selected.current)?.id ?? defaults[0].id;
      selected.current = currentGroupId;
      activeGroup.current = currentGroupId;
      const ready: State = {
        kind: "ready",
        ...result,
        currentGroupId
      };
      current.current = ready;
      setState(ready);
      return ready;
    } catch (failure) {
      if (!abort.signal.aborted && version === generation.current && mounted.current) setState({
        kind: "error",
        message: watchlistError(failure).message,
        canRetry: true
      });
      return null;
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => {
      mounted.current = false;
      generation.current++;
      request.current?.abort();
    };
  }, [refresh]);
  async function submit(action: Action) {
    if (mutationLocked(write.current)) return null;
    const pending = {
      kind: "pending",
      action
    } as const;
    write.current = pending;
    setMutation(pending);
    try {
      const result = action.type === "create" ? (await createWatchlistGroup({
        name: action.name,
        color: action.color
      })).group : action.type === "color" ? (await changeWatchlistGroupColor(action.groupId, action.color)).group : await deleteWatchlistGroup(action.groupId);
      if (mounted.current) {
        const succeeded = {
          kind: "succeeded",
          action,
          result
        } as const;
        write.current = succeeded;
        setMutation(succeeded);
        if (action.type === "create" && "id" in result) selected.current = result.id;
        if (action.type === "delete" && "nextGroupId" in result) selected.current = result.nextGroupId;
        if (action.type === "color" && "id" in result && current.current.kind === "ready") {
          current.current = {
            ...current.current,
            groups: current.current.groups.map(group => group.id === result.id ? result : group)
          };
          setState(current.current);
        }
      }
      return result;
    } catch (failure) {
      if (mounted.current) {
        const next: WatchlistMutation<Action, Result> = failure instanceof WatchlistApiError && failure.outcome === "UNKNOWN" ? {
          kind: "unknown",
          action
        } : {
          kind: "failed",
          action,
          error: watchlistError(failure)
        };
        write.current = next;
        setMutation(next);
      }
      throw failure;
    }
  }
  return {
    state,
    mutation,
    refresh,
    submit,
    // A mutation may nominate a target; only the groups GET activates it.
    currentGroupId: activeGroup.current,
    selectGroup: (id: number, editing: boolean) => {
      if (editing || mutationLocked(write.current) || current.current.kind !== "ready" || !current.current.groups.some(g => g.id === id)) return;
      selected.current = id;
      activeGroup.current = id;
      const next = {
        ...current.current,
        currentGroupId: id
      };
      current.current = next;
      setState(next);
    },
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
