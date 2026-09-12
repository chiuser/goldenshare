import type { RecoveryStatusDto } from "../api/generatedContracts";

export interface RecoveryIdentity {
  authEpoch: number;
  pageGeneration: number;
  requestId: string;
}
export interface WriteRecoveryState extends RecoveryIdentity {
  status: RecoveryStatusDto | null;
  queryUnavailable: boolean;
  inconsistentResponse: boolean;
}
export type RecoveryEvent = RecoveryIdentity & (
  { kind: "status"; status: RecoveryStatusDto } | { kind: "queryFailed" }
);

function sameValue(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (!a || !b || typeof a !== "object" || typeof b !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const left = Object.entries(a), right = Object.entries(b);
  return left.length === right.length && left.every(([key, value]) =>
    Object.hasOwn(b, key) && sameValue(value, (b as Record<string, unknown>)[key]));
}

// Only merges evidence. It cannot send, retry, cancel or release a write.
export function reduceWriteRecovery(current: WriteRecoveryState, event: RecoveryEvent): WriteRecoveryState {
  if (event.authEpoch !== current.authEpoch || event.pageGeneration !== current.pageGeneration
    || event.requestId !== current.requestId) return current;
  if (event.kind === "queryFailed") return { ...current, queryUnavailable: true };
  const next = event.status, previous = current.status;
  if (next.requestId !== current.requestId) return current;
  if (previous) {
    if (BigInt(next.stateVersion) < BigInt(previous.stateVersion)) return current;
    if (next.stateVersion === previous.stateVersion) {
      if (!sameValue(previous, next)) return { ...current, inconsistentResponse: true, queryUnavailable: true };
      return { ...current, queryUnavailable: false, inconsistentResponse: false };
    }
    // A saved receipt is immutable. An unrelated later response cannot undo it.
    if (previous.outcome === "SAVED") return { ...current,
      queryUnavailable: !sameValue(previous.receipt, next.receipt),
      inconsistentResponse: !sameValue(previous.receipt, next.receipt) };
    if (next.operationType !== previous.operationType || !sameValue(next.scope, previous.scope)
      || !sameValue(next.target, previous.target)
      || (previous.outcome === "NOT_SAVED" && next.outcome === "PROCESSING" && next.attemptId === previous.attemptId)) {
      return { ...current, inconsistentResponse: true, queryUnavailable: true };
    }
  }
  return { ...current, status: next, queryUnavailable: false, inconsistentResponse: false };
}

export const mayReturnToEditing = (state: WriteRecoveryState): boolean =>
  state.status?.outcome === "NOT_SAVED" && !state.queryUnavailable && !state.inconsistentResponse;
