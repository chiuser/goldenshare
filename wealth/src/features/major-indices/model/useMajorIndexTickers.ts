import { useEffect, useState } from "react";
import { fetchMarketMajorIndices } from "../api/marketMajorIndicesApi";
import {
  buildMajorIndicesViewModelFromApi,
  buildTopMarketTickersFromMajorIndices,
} from "../api/marketMajorIndicesAdapter";
import type { TopMarketTicker } from "../../../shared/ui/top-market-bar/topMarketBarTypes";

export function useMajorIndexTickers(tradeDate?: string) {
  const [tickers, setTickers] = useState<readonly TopMarketTicker[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    setTickers([]);
    void fetchMarketMajorIndices({ tradeDate }, { signal: controller.signal })
      .then((response) => {
        if (!controller.signal.aborted)
          setTickers(
            buildTopMarketTickersFromMajorIndices(
              buildMajorIndicesViewModelFromApi(response),
            ),
          );
      })
      .catch(() => {
        if (!controller.signal.aborted) setTickers([]);
      });
    return () => controller.abort();
  }, [tradeDate]);
  return tickers;
}
