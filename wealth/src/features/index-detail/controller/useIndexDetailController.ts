import { useEffect, useState } from "react";

import { fetchIndexDetailKline, fetchIndexDetailPageInit } from "../api/indexDetailApiClient";
import { fetchTrendChannel } from "../api/trendChannelApiClient";
import { buildIndexDetailViewModel } from "../api/indexDetailViewModelAdapter";
import { buildTrendChannelViewModel } from "../api/trendChannelAdapter";
import type { IndexDetailViewModel, TrendChannelViewModel } from "../model/indexDetailTypes";

export interface IndexDetailControllerState {
  phase: "loading" | "ready" | "empty" | "error";
  errorMessage: string;
  viewModel: IndexDetailViewModel | null;
  trend: TrendChannelViewModel | null;
  trendPhase: "unavailable" | "loading" | "ready" | "error";
}

export function useIndexDetailController(tsCode: string, search: string): IndexDetailControllerState {
  const [state, setState] = useState<IndexDetailControllerState>(initialState);

  useEffect(() => {
    const controller = new AbortController();
    const searchParams = new URLSearchParams(search);
    const tradeDate = searchParams.get("tradeDate") ?? undefined;
    const debug = searchParams.get("debug") === "1" ? 1 : undefined;
    setState(initialState);

    async function load() {
      try {
        const pageInit = await fetchIndexDetailPageInit({ tsCode, tradeDate, debug }, { signal: controller.signal });
        if (!pageInit.quote || !pageInit.asOfTradeDate) {
          setState({ ...initialState, phase: "empty" });
          return;
        }
        const supportsTrend = pageInit.capabilities.supportsTrendChannel && tsCode.toUpperCase() === "000001.SH";
        setState((current) => ({
          ...current,
          trendPhase: supportsTrend ? "loading" : "unavailable",
        }));

        const klinePromise = fetchIndexDetailKline(
          { tsCode, period: "day", endDate: pageInit.asOfTradeDate, limit: 300, debug },
          { signal: controller.signal },
        );
        const trendPromise = supportsTrend
          ? fetchTrendChannel({ endDate: pageInit.asOfTradeDate, limit: 300 }, { signal: controller.signal })
              .then(buildTrendChannelViewModel)
              .catch((error: unknown) => {
                if (controller.signal.aborted) throw error;
                return null;
              })
          : Promise.resolve(null);

        const [kline, trend] = await Promise.all([klinePromise, trendPromise]);
        if (controller.signal.aborted) return;
        if (kline.bars.length === 0) {
          setState({ ...initialState, phase: "empty", trendPhase: supportsTrend ? "error" : "unavailable" });
          return;
        }
        setState({
          phase: "ready",
          errorMessage: "",
          viewModel: buildIndexDetailViewModel(pageInit, kline),
          trend,
          trendPhase: supportsTrend ? (trend ? "ready" : "error") : "unavailable",
        });
      } catch (error) {
        if (controller.signal.aborted) return;
        setState({
          ...initialState,
          phase: "error",
          errorMessage: error instanceof Error ? error.message : "指数详情数据加载失败",
        });
      }
    }

    void load();
    return () => controller.abort();
  }, [search, tsCode]);

  return state;
}

const initialState: IndexDetailControllerState = {
  phase: "loading",
  errorMessage: "",
  viewModel: null,
  trend: null,
  trendPhase: "unavailable",
};
