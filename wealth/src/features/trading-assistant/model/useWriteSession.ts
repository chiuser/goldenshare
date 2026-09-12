import { useEffect, useRef, useState } from "react";
import { getAuthEpoch } from "../../auth/model/authStorage";
import { getPending, getRecovery, getRecoverableInput, request, TradingAssistantApiError, SaveOutcomeUnknown } from "../api/tradingAssistantApi";
import { parseContract } from "../api/contractValidation";
import type { FieldErrorDto, RecoveryStatusDto } from "../api/generatedContracts";
import { canonicalInput, type AccountingScope, type AccountingOperation, writeOperation } from "./writeOperation";
import { mayReturnToEditing, reduceWriteRecovery, type WriteRecoveryState } from "./writeRecovery";

type Receipt = NonNullable<RecoveryStatusDto["receipt"]>;
export function useWriteSession(scope: AccountingScope) {
  const scopeKey = canonicalInput(scope);
  const generation = useRef(0);
  const active = useRef({ epoch: getAuthEpoch(), generation: 0 });
  const recoveryRef = useRef<WriteRecoveryState | null>(null);
  const original = useRef<{ fingerprint: string; path: string } | null>(null);
  const inFlight = useRef(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<FieldErrorDto[]>([]);
  const [recovery, setRecovery] = useState<WriteRecoveryState | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [editing, setEditing] = useState(false);
  const [lookupVersion, setLookupVersion] = useState(0);
  function publish(next: WriteRecoveryState) { recoveryRef.current = next; setRecovery(next); }
  const isCurrent = (identity: typeof active.current) => identity === active.current && identity.epoch === getAuthEpoch();

  useEffect(() => {
    const controller = new AbortController();
    const identity = { epoch: getAuthEpoch(), generation: ++generation.current };
    active.current = identity; recoveryRef.current = null; original.current = null; inFlight.current = false;
    setReady(false); setBusy(true); setError(null); setRecovery(null); setReceipt(null); setEditing(false); setFieldErrors([]);
    const selected = JSON.parse(scopeKey) as AccountingScope;
    getPending(selected.scopeType, "accountId" in selected ? selected.accountId : undefined, controller.signal).then(result => {
      if (!isCurrent(identity)) return;
      if (result.pendingRequest) {
        if (canonicalInput(result.pendingRequest.scope) !== scopeKey) throw new Error("Scope mismatch");
        publish({ authEpoch: identity.epoch, pageGeneration: identity.generation, requestId: result.pendingRequest.requestId,
          status: result.pendingRequest, queryUnavailable: false, inconsistentResponse: false });
      }
      setReady(true);
    }).catch(() => { if (isCurrent(identity)) setError("暂时无法核对该账户的保存状态，请重新读取"); })
      .finally(() => { if (isCurrent(identity)) setBusy(false); });
    return () => { controller.abort(); active.current = { epoch: -1, generation: ++generation.current }; };
  }, [scopeKey, lookupVersion]);

  async function check() {
    const previous = recoveryRef.current, identity = active.current;
    if (!previous || inFlight.current) return;
    inFlight.current = true; setBusy(true);
    try {
      const status = await getRecovery(previous.requestId);
      if (!isCurrent(identity)) return;
      const next = reduceWriteRecovery(recoveryRef.current!, { ...previous, kind: "status", status });
      publish(next);
      if (next.status?.receipt) setReceipt(next.status.receipt);
    } catch {
      if (isCurrent(identity)) publish(reduceWriteRecovery(recoveryRef.current!, { ...previous, kind: "queryFailed" }));
    } finally { if (isCurrent(identity)) { inFlight.current = false; setBusy(false); } }
  }

  async function restore() {
    const known = recoveryRef.current, identity = active.current;
    if (!known || !mayReturnToEditing(known) || !known.status || inFlight.current) return null;
    inFlight.current = true; setBusy(true); setError(null);
    try {
      const restored = await getRecoverableInput(known.status);
      if (!isCurrent(identity)) return null;
      if (restored.inputSchemaVersion !== "1") throw new Error("Unsupported retained input version");
      const spec = writeOperation(restored.operationType as AccountingOperation, scope, restored.target);
      original.current = { fingerprint: canonicalInput(restored.input), path: spec.path };
      setEditing(true);
      return restored;
    } catch { if (isCurrent(identity)) setError("原输入暂时无法读取，请稍后重试；当前填写内容仍保留"); return null; }
    finally { if (isCurrent(identity)) { inFlight.current = false; setBusy(false); } }
  }

  async function save(operation: AccountingOperation, input: Record<string, unknown>, target: RecoveryStatusDto["target"] = null) {
    if (!ready || inFlight.current || receipt || (recoveryRef.current && !editing)) return null;
    const identity = active.current;
    if (!isCurrent(identity)) return null;
    const spec = writeOperation(operation, scope, target), fingerprint = canonicalInput(input);
    const previous = recoveryRef.current;
    const retry = previous && mayReturnToEditing(previous) && original.current?.fingerprint === fingerprint && original.current.path === spec.path;
    const requestId = retry ? previous.requestId : crypto.randomUUID(), attemptId = crypto.randomUUID();
    const body = parseContract(spec.commandModel, { ...input, requestId, attemptId,
      ...(retry ? { expectedRequestStateVersion: previous.status!.stateVersion } : {}) });
    original.current = { fingerprint, path: spec.path };
    publish({ authEpoch: identity.epoch, pageGeneration: identity.generation, requestId,
      status: null, queryUnavailable: false, inconsistentResponse: false });
    setEditing(false); inFlight.current = true; setBusy(true); setError(null); setFieldErrors([]);
    try {
      const result = await request(spec.path, spec.receiptModel, { method: spec.method, body, write: true });
      if (!isCurrent(identity)) return null;
      if (result.requestId !== requestId || result.attemptId !== attemptId || result.operationType !== operation
        || ("accountId" in scope && "accountId" in result.result && result.result.accountId !== scope.accountId)
        || (target?.kind === "TRADE" && (!("tradeId" in result.result) || result.result.tradeId !== target.recordId))
        || (target?.kind === "CASH_FLOW" && (!("cashFlowId" in result.result) || result.result.cashFlowId !== target.recordId))) throw new SaveOutcomeUnknown();
      setReceipt(result); return result;
    } catch (failure) {
      if (!isCurrent(identity)) return null;
      if (failure instanceof TradingAssistantApiError) setFieldErrors(failure.details.fieldErrors);
      // An HTTP code is not a stop proof. Only GET can unlock this operation.
      try {
        const status = await getRecovery(requestId);
        if (isCurrent(identity)) {
          const next = reduceWriteRecovery(recoveryRef.current!, { ...recoveryRef.current!, kind: "status", status });
          publish(next); if (next.status?.receipt) setReceipt(next.status.receipt);
        }
      } catch { if (isCurrent(identity)) publish(reduceWriteRecovery(recoveryRef.current!, { ...recoveryRef.current!, kind: "queryFailed" })); }
      return null;
    } finally { if (isCurrent(identity)) { inFlight.current = false; setBusy(false); } }
  }

  return { ready, busy, error, fieldErrors, recovery, receipt, editing,
    canSave: ready && !busy && !receipt && (!recovery || editing),
    check, restore, save, retryInitialLookup: () => { if (!recoveryRef.current && !inFlight.current) setLookupVersion(v => v + 1); } };
}
