import { useCallback, useEffect, useMemo, useState } from "react";

import {
  buildMajorIndicesViewModelFromApi,
  buildTopMarketTickersFromMajorIndices,
} from "../../../features/major-indices/api/marketMajorIndicesAdapter";
import { fetchMarketMajorIndices } from "../../../features/major-indices/api/marketMajorIndicesApi";
import {
  buildMarketPageContextViewModelFromApi,
  type MarketPageContextViewModel,
} from "../../../features/market-context/api/marketPageContextAdapter";
import {
  fetchMarketPageContext,
  readMarketContextRequest,
} from "../../../features/market-context/api/marketPageContextApi";
import type { TopMarketTicker } from "../../../shared/ui/top-market-bar/topMarketBarTypes";

const PAGE_CONTEXT_TIMEOUT_MS = 5000;
const MAJOR_INDICES_TIMEOUT_MS = 5000;

export interface WealthExplorationShellModel {
  contextState: "loading" | "ready" | "error";
  pageContext: MarketPageContextViewModel | null;
  tickers: readonly TopMarketTicker[];
  retryContext: () => void;
}

export interface WealthExplorationShellState {
  model: WealthExplorationShellModel;
  contextErrorMessage: string | null;
}

function readRouteSearch(search: string | undefined): string {
  if (search !== undefined) return search;
  return typeof window === "undefined" ? "" : window.location.search;
}

export function useWealthExplorationShell(search?: string): WealthExplorationShellState {
  const routeSearch = readRouteSearch(search);
  const contextRequest = useMemo(() => readMarketContextRequest(routeSearch), [routeSearch]);
  const [contextAttempt, setContextAttempt] = useState(0);
  const [contextState, setContextState] = useState<WealthExplorationShellModel["contextState"]>("loading");
  const [pageContext, setPageContext] = useState<MarketPageContextViewModel | null>(null);
  const [contextErrorMessage, setContextErrorMessage] = useState<string | null>(null);
  const [tickers, setTickers] = useState<readonly TopMarketTicker[]>([]);
  const retryContext = useCallback(() => setContextAttempt((value) => value + 1), []);

  useEffect(() => {
    let canceled = false;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), PAGE_CONTEXT_TIMEOUT_MS);
    setContextState("loading");
    setPageContext(null);
    setContextErrorMessage(null);
    setTickers([]);

    fetchMarketPageContext(contextRequest, { signal: controller.signal })
      .then((payload) => {
        if (canceled) return;
        setPageContext(buildMarketPageContextViewModelFromApi(payload));
        setContextState("ready");
      })
      .catch((error) => {
        if (canceled) return;
        const timedOut = error instanceof DOMException && error.name === "AbortError";
        setContextState("error");
        setPageContext(null);
        setContextErrorMessage(
          timedOut
            ? "页面时间上下文请求超时，请稍后重试。"
            : error instanceof Error
              ? error.message
              : "页面时间上下文加载失败。",
        );
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      canceled = true;
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [contextRequest.debug, contextRequest.market, contextRequest.tradeDate, contextAttempt]);

  useEffect(() => {
    if (!pageContext) {
      setTickers([]);
      return;
    }
    let canceled = false;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), MAJOR_INDICES_TIMEOUT_MS);
    setTickers([]);

    fetchMarketMajorIndices({
      market: pageContext.market,
      tradeDate: pageContext.tradeDate,
      debug: contextRequest.debug,
    }, { signal: controller.signal })
      .then((payload) => {
        if (canceled) return;
        setTickers(buildTopMarketTickersFromMajorIndices(buildMajorIndicesViewModelFromApi(payload)));
      })
      .catch(() => {
        if (!canceled) setTickers([]);
      })
      .finally(() => window.clearTimeout(timeoutId));

    return () => {
      canceled = true;
      controller.abort();
      window.clearTimeout(timeoutId);
    };
  }, [contextRequest.debug, pageContext?.market, pageContext?.tradeDate]);

  return {
    model: { contextState, pageContext, tickers, retryContext },
    contextErrorMessage,
  };
}
