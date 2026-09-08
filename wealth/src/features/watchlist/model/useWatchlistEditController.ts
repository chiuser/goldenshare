import { useEffect, useRef, useState } from "react";
import { batchWatchlistItems, WatchlistApiError } from "../api/watchlistApi";
import type { WatchlistBatchAction, WatchlistBatchActionResponseDto } from "../api/watchlistApiTypes";
import { mutationLocked, watchlistError, type WatchlistMutation } from "./watchlistTypes";
type Action = {
  groupId: number;
  type: WatchlistBatchAction;
  membershipIds: number[];
  targetGroupIds: number[];
};
export type WatchlistEditDialog = "move" | "add" | "remove" | "color" | "delete" | null;
export function useWatchlistEditController(groupId: number | undefined, loadedIds: number[], maxSelection: number) {
  const [editingGroupId, setEditingGroupId] = useState<number | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [dialog, setDialog] = useState<WatchlistEditDialog>(null);
  const [mutation, setMutation] = useState<WatchlistMutation<Action, WatchlistBatchActionResponseDto>>({
    kind: "idle"
  });
  const write = useRef(mutation);
  write.current = mutation;
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const clear = () => {
    setSelectedIds(new Set());
    setDialog(null);
  };
  const finish = () => {
    if (!mutationLocked(write.current)) {
      clear();
      setEditingGroupId(null);
    }
  };
  async function submit(type: WatchlistBatchAction, targetGroupIds: number[] = []) {
    if (mutationLocked(write.current) || editingGroupId === null || editingGroupId !== groupId || selectedIds.size === 0 || selectedIds.size > maxSelection) return null;
    const action = {
      groupId: editingGroupId,
      type,
      membershipIds: [...selectedIds],
      targetGroupIds
    };
    const pending = {
      kind: "pending",
      action
    } as const;
    write.current = pending;
    setMutation(pending);
    try {
      const result = await batchWatchlistItems(action.groupId, type, action.membershipIds, targetGroupIds);
      if (mounted.current) {
        const next = {
          kind: "succeeded",
          action,
          result
        } as const;
        write.current = next;
        setMutation(next);
        clear();
      }
      return result;
    } catch (failure) {
      if (mounted.current) {
        const next: WatchlistMutation<Action, WatchlistBatchActionResponseDto> = failure instanceof WatchlistApiError && failure.outcome === "UNKNOWN" ? {
          kind: "unknown",
          action
        } : {
          kind: "failed",
          action,
          error: watchlistError(failure)
        };
        write.current = next;
        setMutation(next);
        if (failure instanceof WatchlistApiError && failure.code === "WL_SELECTION_STALE") clear();
      }
      throw failure;
    }
  }
  return {
    isEditing: editingGroupId !== null,
    selectedIds,
    dialog,
    mutation,
    submit,
    clear,
    finish,
    enter: () => {
      if (groupId !== undefined) {
        clear();
        setEditingGroupId(groupId);
      }
    },
    setDialog: (value: WatchlistEditDialog) => {
      if (!mutationLocked(write.current)) setDialog(value);
    },
    toggle: (id: number) => {
      if (mutationLocked(write.current) || editingGroupId !== groupId || !loadedIds.includes(id)) return;
      setSelectedIds(previous => {
        const next = new Set(previous);
        if (next.has(id)) next.delete(id);else if (next.size < maxSelection) next.add(id);
        return next;
      });
    },
    reconciled: () => {
      if (write.current.kind === "unknown") {
        write.current = {
          kind: "idle"
        };
        setMutation(write.current);
        clear();
      }
    }
  };
}
