import { useEffect, useRef, useState } from "react";
import { getAuthEpoch } from "../../auth/model/authStorage";
import type { PositionsAnalysis } from "../api/generatedContracts";
import { getPositionsAnalysis } from "../api/positionsApi";
import { TradingAssistantApiError } from "../api/tradingAssistantApi";

/** A child of the positions read, never a second polling loop or version selector. */
export function useHoldingAnalysis(selected: string, token: string, onRefresh: () => void) {
  const [state, setState] = useState<{ key: string; data: PositionsAnalysis | null; error: boolean } | null>(null);
  const [retry, setRetry] = useState(0);
  const refresh = useRef(onRefresh); refresh.current = onRefresh;
  const key = `${selected}:${token}`;
  useEffect(() => {
    let abort: AbortController | null = null;
    const load = () => {
      abort?.abort();
      if (document.visibilityState === "hidden") return;
      const controller = new AbortController(), epoch = getAuthEpoch();
      abort = controller;
      setState({ key, data: null, error: false });
      void getPositionsAnalysis(selected, token, controller.signal).then(data => {
        if (!controller.signal.aborted && epoch === getAuthEpoch()) setState({ key, data, error: false });
      }).catch(error => {
        if (controller.signal.aborted || epoch !== getAuthEpoch()) return;
        if (error instanceof TradingAssistantApiError && error.details.code === "TA_READ_CONTEXT_CHANGED") refresh.current();
        else setState({ key, data: null, error: true });
      });
    };
    load(); document.addEventListener("visibilitychange", load);
    return () => { abort?.abort(); document.removeEventListener("visibilitychange", load); };
  }, [key, selected, token, retry]);
  const current = state?.key === key ? state : null;
  return { data: current?.data ?? null, error: current?.error ?? false, retry: () => setRetry(value => value + 1) };
}
