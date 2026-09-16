import { useEffect, useRef, useState } from "react";
import { getAuthEpoch } from "../../auth/model/authStorage";
import { getRules, type RuleKind } from "../api/rulesApi";
import type { AlertsResponse, PlansResponse, AlertsQuery } from "../api/generatedContracts";

export function useRules(kind: RuleKind, selected: string | null, status: AlertsQuery["status"], keyword: string, revision: number) {
  const [data, setData] = useState<PlansResponse | AlertsResponse | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const active = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const cursorRef = useRef<string | null>(null);
  const inFlight = useRef(false);
  const loadRef = useRef<(cursor: string | null) => Promise<void>>(async () => {});
  useEffect(() => {
    const gen = ++generation.current, epoch = getAuthEpoch();
    const controller = new AbortController(); active.current = controller;
    cursorRef.current = null; inFlight.current = false; setData(null); setError(false);
    async function load(cursor: string | null) {
      if (inFlight.current) return;
      inFlight.current = true; setLoading(true); setError(false);
      try {
        const query = { status, keyword: keyword.trim() || null, cursor,
          ...(kind === "PLAN" ? selected && selected !== "ALL" ? { accountMode: "SINGLE" as const, accountId: selected } : { accountMode: "ALL" as const } : {}) };
        const result = await getRules(kind, query, controller.signal);
        if (gen !== generation.current || epoch !== getAuthEpoch()) return;
        cursorRef.current = result.nextCursor;
        setData(previous => cursor && previous ? { ...result, items: [...previous.items, ...result.items] } as typeof result : result);
      } catch { if (gen === generation.current && epoch === getAuthEpoch() && !controller.signal.aborted) setError(true); }
      finally { if (gen === generation.current && epoch === getAuthEpoch()) { inFlight.current = false; setLoading(false); } }
    }
    loadRef.current = load; void load(null);
    return () => { ++generation.current; controller.abort(); };
  }, [kind, selected, status, keyword, revision, retry]);
  return { data, loading, error, refresh: () => setRetry(v => v + 1), more: () => void loadRef.current(cursorRef.current) };
}
