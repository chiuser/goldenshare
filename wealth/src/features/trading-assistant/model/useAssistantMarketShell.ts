import { useEffect, useState } from "react";
import { fetchMarketMajorIndices } from "../../major-indices/api/marketMajorIndicesApi";
import { buildMajorIndicesViewModelFromApi, buildTopMarketTickersFromMajorIndices } from "../../major-indices/api/marketMajorIndicesAdapter";
import type { PageSessionStatus } from "../../../shared/ui/page-breadcrumb/PageBreadcrumb";
import type { TopMarketTicker } from "../../../shared/ui/top-market-bar/topMarketBarTypes";

export function useAssistantMarketShell() {
  const [data, setData] = useState<{ tickers: readonly TopMarketTicker[]; sessionStatus: PageSessionStatus } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void fetchMarketMajorIndices({}, { signal: controller.signal }).then(response => {
      if (controller.signal.aborted) return;
      setData({ tickers: buildTopMarketTickersFromMajorIndices(buildMajorIndicesViewModelFromApi(response)), sessionStatus: response.tradingDay.sessionStatus });
    }).catch(() => { if (!controller.signal.aborted) setData(null); });
    return () => controller.abort();
  }, []);
  return data;
}
