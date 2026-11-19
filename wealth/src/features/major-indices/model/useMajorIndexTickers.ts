import { useEffect, useState } from "react";
import { fetchMarketMajorIndices } from "../api/marketMajorIndicesApi";
import {
  buildMajorIndicesViewModelFromApi,
  buildTopMarketTickersFromMajorIndices,
} from "../api/marketMajorIndicesAdapter";
import type { TopMarketTicker } from "../../../shared/ui/top-market-bar/topMarketBarTypes";

const EMPTY_TICKERS: readonly TopMarketTicker[] = [];

export function useMajorIndexTickers(tradeDate?: string, enabled = true) {
  const [snapshot, setSnapshot] = useState<{
    tradeDate: string | undefined;
    tickers: readonly TopMarketTicker[];
  } | null>(null);
  useEffect(() => {
    setSnapshot(null);
    if (!enabled) return;
    const controller = new AbortController();
    void fetchMarketMajorIndices({ tradeDate }, { signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return;
        setSnapshot({
          tradeDate,
          tickers: buildTopMarketTickersFromMajorIndices(buildMajorIndicesViewModelFromApi(response)),
        });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSnapshot(null);
      });
    return () => controller.abort();
  }, [enabled, tradeDate]);
  return enabled && snapshot && snapshot.tradeDate === tradeDate ? snapshot.tickers : EMPTY_TICKERS;
}
