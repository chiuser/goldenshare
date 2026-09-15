import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { getAuthEpoch } from "../../auth/model/authStorage";
import type { Coverage, ReadContext } from "../api/generatedContracts";
import { TradingAssistantApiError } from "../api/tradingAssistantApi";
import { getCalculationStatus } from "../api/positionsApi";
import { CALCULATION_READ_POLICY } from "./calculationReadPolicy";

type Basis = { readContext: ReadContext; coverage: Coverage };
export const ReturnReadActiveContext = createContext(true);
/** Every visible result belongs to one selection, auth epoch and fixed read context. */
export function useReturnRead<T extends Basis>(identity: string, load: (signal: AbortSignal) => Promise<T>, onChanged?: () => void) {
  const active = useContext(ReturnReadActiveContext);
  const [result, setResult] = useState<{ key: string; data: T } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const callbacks = useRef({ load, onChanged }); callbacks.current = { load, onChanged };
  const terminal = useRef(new Set<string>());
  const key = `${identity}:${version}`;
  const refresh = useCallback(() => setVersion(v => v + 1), []);
  useEffect(() => {
    if (!active) return;
    const abort = new AbortController(), epoch = getAuthEpoch();
    const current = () => !abort.signal.aborted && epoch === getAuthEpoch();
    const visible = () => { if (document.visibilityState === "hidden") abort.abort(); else refresh(); };
    document.addEventListener("visibilitychange", visible);
    setFailure(null);
    if (document.visibilityState !== "hidden") void callbacks.current.load(abort.signal).then(data => {
      if (current()) setResult({ key, data });
    }).catch(error => {
      if (!current()) return;
      setFailure(key); setResult(null);
      if (error instanceof TradingAssistantApiError && error.details.code === "TA_READ_CONTEXT_CHANGED") callbacks.current.onChanged?.();
    });
    return () => { abort.abort(); document.removeEventListener("visibilitychange", visible); };
  }, [key, refresh, active]);
  const data = result?.key === key ? result.data : null;
  useEffect(() => {
    if (!data || !active) return;
    const token = data.readContext.contextToken, epoch = getAuthEpoch();
    const pending = new Map(data.coverage.accounts.filter(a => ["Delayed", "Partial", "Recalculating"].includes(a.dataStatus)
      && !terminal.current.has(`${token}:${a.accountId}`)).map(a => [a.accountId, Date.now() + CALCULATION_READ_POLICY.activeDelayMs]));
    const abort = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const current = () => !abort.signal.aborted && epoch === getAuthEpoch() && document.visibilityState !== "hidden";
    const stopHidden = () => { if (document.visibilityState === "hidden") { abort.abort(); clearTimeout(timer); } };
    document.addEventListener("visibilitychange", stopHidden);
    const schedule = () => { if (pending.size && current()) timer = setTimeout(check, Math.max(0, Math.min(...pending.values()) - Date.now())); };
    async function check() {
      try {
        for (const [id, due] of pending) {
          if (!current()) return;
          if (due > Date.now()) continue;
          const status = await getCalculationStatus(id, abort.signal);
          if (!current()) return;
          const reference = data!.readContext.accounts.find(a => a.accountId === id);
          if (status.stage === "PUBLISHED" || status.stage === "FAILED") {
            terminal.current.add(`${token}:${id}`);
            // A delayed historical range can remain incomplete in an already
            // published generation. Remounting its parent cannot fill that gap.
            if (status.stage === "PUBLISHED" && status.calculationTargetVersion === reference?.calculationTargetVersion
              && status.publishedGenerationId === reference?.publishedGenerationId) { pending.delete(id); continue; }
            callbacks.current.onChanged ? callbacks.current.onChanged() : refresh(); return;
          }
          if (status.calculationTargetVersion !== reference?.calculationTargetVersion) {
            callbacks.current.onChanged ? callbacks.current.onChanged() : refresh(); return;
          }
          pending.set(id, Date.now() + (status.stage === "WAITING_DATA" ? CALCULATION_READ_POLICY.waitingDataDelayMs : CALCULATION_READ_POLICY.activeDelayMs));
        }
        schedule();
      } catch { if (current()) setFailure(key); }
    }
    schedule();
    return () => { abort.abort(); clearTimeout(timer); document.removeEventListener("visibilitychange", stopHidden); };
  }, [data, key, refresh, active]);
  return { data, error:failure === key, loading:data === null && failure !== key, refresh };
}
