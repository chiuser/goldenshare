import { useCallback, useEffect, useRef, useState } from "react";
import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { getAuthEpoch } from "../../auth/model/authStorage";
import { getAccounts, READ_TIMEOUT_MS } from "../api/tradingAssistantApi";
import type { AccountSummary } from "../api/generatedContracts";
import { rememberAccountSelection, restoreAccountSelection } from "./accountPreference";

type AccountsState = { userId: number; accounts: AccountSummary[]; selected: string | null; epoch: number };
export function useTradingAccounts() {
  const [state, setState] = useState<AccountsState | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const current = useRef<AccountsState | null>(null);
  const requestNumber = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(async (selectAccountId?: string) => {
    const epoch = getAuthEpoch(), number = ++requestNumber.current;
    controller.current?.abort();
    const abort = new AbortController(); controller.current = abort;
    setLoading(true); setError(false);
    let timer: number | undefined;
    const timeout = new Promise<never>((_, reject) => {
      timer = window.setTimeout(() => { abort.abort(); reject(new Error("Account read timed out")); }, READ_TIMEOUT_MS);
    });
    const active = () => number === requestNumber.current && epoch === getAuthEpoch() && !abort.signal.aborted;
    try {
      const [owner, result] = await Promise.race([timeout, Promise.all([
        wealthFetch("/api/v1/auth/me", { signal: abort.signal, cache: "no-store" }).then(async response => {
          if (!response.ok) throw new Error("Identity unavailable");
          const value: unknown = await response.json();
          if (!value || typeof value !== "object" || !("id" in value) || typeof value.id !== "number"
            || !Number.isSafeInteger(value.id) || value.id <= 0) throw new Error("Invalid identity");
          return value.id;
        }), getAccounts(abort.signal),
      ])]);
      if (!active()) return;
      const previous = current.current;
      const wanted = selectAccountId ?? (previous?.epoch === epoch && previous.userId === owner ? previous.selected : null);
      const selected = result.items.length && (wanted === "ALL" || result.items.some(account => account.accountId === wanted))
        ? wanted : restoreAccountSelection(owner, result.items);
      const next = { userId: owner, accounts: result.items, selected, epoch };
      current.current = next; setState(next);
      if (selectAccountId && selected === selectAccountId) rememberAccountSelection(owner, selectAccountId, result.items);
    } catch {
      if (number === requestNumber.current && epoch === getAuthEpoch()) { setError(true); throw new Error("账户信息暂时无法读取"); }
    } finally {
      window.clearTimeout(timer);
      if (number === requestNumber.current && epoch === getAuthEpoch()) setLoading(false);
    }
  }, []);
  useEffect(() => {
    void refresh().catch(() => undefined);
    return () => { ++requestNumber.current; controller.current?.abort(); current.current = null; };
  }, [refresh]);
  function select(selected: string) {
    const known = current.current;
    if (!known || known.epoch !== getAuthEpoch() || (selected !== "ALL" && !known.accounts.some(a => a.accountId === selected))) return;
    rememberAccountSelection(known.userId, selected, known.accounts);
    const next = { ...known, selected }; current.current = next; setState(next);
  }
  // Auth changes discard all private facts; the page is also keyed by auth epoch.
  const visible = state?.epoch === getAuthEpoch() ? state : null;
  return { state: visible, error, loading, refresh, select };
}
