import { useCallback, useEffect, useRef, useState } from "react";

import { fetchStockTrendChannel } from "../api/stockTrendChannelApiClient";
import {
  buildStockTrendChannelViewModel,
  type StockTrendChannelViewModel,
} from "../api/stockTrendChannelViewModelAdapter";

export type StockTrendChannelPhase = "unavailable" | "idle" | "loading" | "ready" | "error";

interface StockTrendChannelSnapshot {
  data: StockTrendChannelViewModel | null;
  errorMessage: string;
  phase: StockTrendChannelPhase;
  requestKey: string;
}

export interface StockTrendChannelController {
  data: StockTrendChannelViewModel | null;
  ensure: () => void;
  errorMessage: string;
  phase: StockTrendChannelPhase;
  retry: () => void;
}

export function useStockTrendChannel({
  enabled,
  endDate,
  tsCode,
}: {
  enabled: boolean;
  endDate: string | null;
  tsCode: string;
}): StockTrendChannelController {
  const requestKey = enabled && endDate ? `${tsCode}|${endDate}` : "";
  const [snapshot, setSnapshot] = useState<StockTrendChannelSnapshot>(() => initialSnapshot(requestKey, enabled));
  const activeKeyRef = useRef(requestKey);
  const requestIdRef = useRef(0);
  const abortRef = useRef<AbortController | null>(null);
  activeKeyRef.current = requestKey;

  useEffect(() => {
    requestIdRef.current += 1;
    abortRef.current?.abort();
    abortRef.current = null;
    setSnapshot(initialSnapshot(requestKey, enabled));
    return () => abortRef.current?.abort();
  }, [enabled, requestKey]);

  const visible = snapshot.requestKey === requestKey
    ? snapshot
    : initialSnapshot(requestKey, enabled);

  const load = useCallback(() => {
    if (!enabled || !endDate || !requestKey) return;
    if (
      snapshot.requestKey === requestKey
      && (snapshot.phase === "loading" || snapshot.phase === "ready")
    ) return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const requestId = ++requestIdRef.current;
    setSnapshot({ data: null, errorMessage: "", phase: "loading", requestKey });
    void fetchStockTrendChannel(
      { tsCode, endDate, limit: 300 },
      { signal: controller.signal },
    ).then((payload) => {
      if (
        controller.signal.aborted
        || requestIdRef.current !== requestId
        || activeKeyRef.current !== requestKey
      ) return;
      setSnapshot({
        data: buildStockTrendChannelViewModel(payload),
        errorMessage: "",
        phase: "ready",
        requestKey,
      });
    }).catch((error: unknown) => {
      if (
        controller.signal.aborted
        || requestIdRef.current !== requestId
        || activeKeyRef.current !== requestKey
      ) return;
      setSnapshot({
        data: null,
        errorMessage: error instanceof Error ? error.message : "股票趋势通道加载失败",
        phase: "error",
        requestKey,
      });
    });
  }, [enabled, endDate, requestKey, snapshot.phase, snapshot.requestKey, tsCode]);

  return {
    data: visible.data,
    ensure: load,
    errorMessage: visible.errorMessage,
    phase: visible.phase,
    retry: load,
  };
}

function initialSnapshot(requestKey: string, enabled: boolean): StockTrendChannelSnapshot {
  return {
    data: null,
    errorMessage: "",
    phase: enabled && requestKey ? "idle" : "unavailable",
    requestKey,
  };
}
