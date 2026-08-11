import { useEffect, useState } from "react";

import { fetchIndexDetailWeights } from "../api/indexDetailApiClient";
import type { IndexDetailWeightsResponseDto } from "../api/indexDetailApiTypes";

const indexWeightsCache = new Map<string, IndexDetailWeightsResponseDto>();

export function useIndexWeights(params: {
  active: boolean;
  asOfTradeDate: string | null;
  debug?: 0 | 1;
  tsCode: string;
}) {
  const { active, asOfTradeDate, debug, tsCode } = params;
  const cacheKey = `${tsCode.toUpperCase()}|${asOfTradeDate ?? ""}`;
  const cached = indexWeightsCache.get(cacheKey) ?? null;
  const [data, setData] = useState<IndexDetailWeightsResponseDto | null>(cached);
  const [phase, setPhase] = useState<"idle" | "loading" | "ready" | "empty" | "error">(
    cached ? (cached.rows.length > 0 ? "ready" : "empty") : "idle",
  );
  const [errorMessage, setErrorMessage] = useState("");
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    const nextCached = indexWeightsCache.get(cacheKey) ?? null;
    setData(nextCached);
    setPhase(nextCached ? (nextCached.rows.length > 0 ? "ready" : "empty") : "idle");
    setErrorMessage("");
  }, [cacheKey]);

  useEffect(() => {
    if (!active || !asOfTradeDate || indexWeightsCache.has(cacheKey)) return;
    const controller = new AbortController();
    setPhase("loading");
    setErrorMessage("");
    fetchIndexDetailWeights({ tsCode, tradeDate: asOfTradeDate, debug }, { signal: controller.signal })
      .then((payload) => {
        indexWeightsCache.set(cacheKey, payload);
        setData(payload);
        setPhase(payload.rows.length > 0 ? "ready" : "empty");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setPhase("error");
        setErrorMessage(error instanceof Error ? error.message : "权重股数据加载失败");
      });
    return () => controller.abort();
  }, [active, asOfTradeDate, cacheKey, debug, retryToken, tsCode]);

  return {
    data,
    errorMessage,
    phase,
    retry: () => setRetryToken((value) => value + 1),
  };
}
