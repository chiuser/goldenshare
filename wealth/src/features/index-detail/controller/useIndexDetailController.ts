import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchIndexDetailKline,
  fetchIndexDetailPageInit,
  IndexDetailApiError,
} from "../api/indexDetailApiClient";
import { loadIndexNineTurnSeries } from "../api/indexNineTurnLoader";
import { fetchTrendChannel } from "../api/trendChannelApiClient";
import {
  buildEmptyIndexDetailViewModel,
  buildIndexDetailViewModel,
} from "../api/indexDetailViewModelAdapter";
import { buildTrendChannelViewModel } from "../api/trendChannelAdapter";
import { DAILY_CHART_PAGE_SIZE } from "../../../shared/charts/dailyChartRequestLimits";
import { readSseDailyCursor, useIndexDailyHistory, type IndexDailyHistory, type IndexDailyHistorySeed } from "./useIndexDailyHistory";
import {
  collectIndexPartialReasons,
  normalizeIndexTsCode,
  resolveIndexDataPagePhase,
} from "../model/indexDetailState";
import type {
  IndexDataPagePhase,
  IndexDetailViewModel,
  IndexPagePhase,
  TrendChannelViewModel,
} from "../model/indexDetailTypes";

interface IndexDetailControllerSnapshot {
  basePhase: IndexDataPagePhase;
  errorCode: string;
  errorMessage: string;
  pagePartialReasons: string[];
  partialReasons: string[];
  phase: IndexPagePhase;
  requestKey: string;
  historySeed: IndexDailyHistorySeed | null;
  trend: TrendChannelViewModel | null;
  trendPhase: "unavailable" | "loading" | "ready" | "error";
  viewModel: IndexDetailViewModel | null;
}

export interface IndexDetailControllerState extends IndexDetailControllerSnapshot {
  history: IndexDailyHistory;
  retry: () => void;
  retryTrend: () => void;
}

export function useIndexDetailController(tsCode: string, tradeDate: string | undefined, dailyActive = true,
    loadPageInit = fetchIndexDetailPageInit, loadDailyKline = fetchIndexDetailKline, loadNineTurn = loadIndexNineTurnSeries): IndexDetailControllerState {
  const normalizedTsCode = normalizeIndexTsCode(tsCode);
  const [retryToken, setRetryToken] = useState(0);
  const requestKey = `${normalizedTsCode}|${tradeDate ?? ""}|${retryToken}`;
  const [state, setState] = useState<IndexDetailControllerSnapshot>(() => createInitialState(requestKey));
  const requestIdRef = useRef(0);
  const trendControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const requestId = ++requestIdRef.current;
    trendControllerRef.current?.abort();
    trendControllerRef.current = null;
    setState(createInitialState(requestKey));

    async function load() {
      try {
        const pageInit = await loadPageInit(
          { tsCode: normalizedTsCode, tradeDate },
          { signal: controller.signal },
        );
        if (!isCurrent(requestIdRef, requestId, controller.signal)) return;
        if (pageInit.index.tsCode !== normalizedTsCode) throw new Error("指数详情返回的代码与请求不一致");

        if (pageInit.dataStatus.status === "EMPTY" || !pageInit.quote || !pageInit.asOfTradeDate) {
          setState({
            ...createInitialState(requestKey),
            phase: "empty",
            viewModel: buildEmptyIndexDetailViewModel(pageInit),
          });
          return;
        }

        const supportsTrend = pageInit.capabilities.supportsTrendChannel && normalizedTsCode === "000001.SH";
        setState((current) => ({
          ...current,
          trendPhase: supportsTrend ? "loading" : "unavailable",
          viewModel: null,
        }));
        if (supportsTrend) {
          const trendController = new AbortController();
          trendControllerRef.current = trendController;
          void requestTrend(pageInit.asOfTradeDate, trendController.signal)
            .then((trend) => commitTrendSuccess(setState, requestIdRef, requestId, trend))
            .catch((error: unknown) => {
              if (!trendController.signal.aborted) commitTrendFailure(setState, requestIdRef, requestId, error);
            });
        }

        const kline = await loadDailyKline(
          { tsCode: normalizedTsCode, period: "day", endDate: pageInit.asOfTradeDate, limit: DAILY_CHART_PAGE_SIZE },
          { signal: controller.signal },
        );
        if (!isCurrent(requestIdRef, requestId, controller.signal)) return;
        if (kline.indexRef.tsCode !== normalizedTsCode) throw new Error("指数K线返回的代码与请求不一致");
        const nextEndDate = normalizedTsCode === "000001.SH"
          ? readSseDailyCursor(kline, pageInit.asOfTradeDate)
          : null;
        if (kline.dataStatus.status === "EMPTY" || kline.bars.length === 0) {
          trendControllerRef.current?.abort();
          setState({
            ...createInitialState(requestKey),
            phase: "empty",
            viewModel: buildEmptyIndexDetailViewModel(pageInit),
          });
          return;
        }

        const basePhase = resolveIndexDataPagePhase(pageInit, kline);
        const pagePartialReasons = collectIndexPartialReasons(pageInit, kline);
        const viewModel = buildIndexDetailViewModel(pageInit, kline);
        setState((current) => {
          const trendFailed = current.trendPhase === "error";
          return {
            ...current,
            basePhase,
            errorCode: "",
            errorMessage: "",
            pagePartialReasons,
            partialReasons: trendFailed ? mergeReasons(pagePartialReasons, ["趋势通道"]) : pagePartialReasons,
            phase: trendFailed ? "partial" : basePhase,
            historySeed: normalizedTsCode === "000001.SH" ? { viewModel, nextEndDate } : null,
            viewModel,
          };
        });
      } catch (error) {
        if (!isCurrent(requestIdRef, requestId, controller.signal)) return;
        trendControllerRef.current?.abort();
        const failure = resolvePageFailure(error);
        setState({
          ...createInitialState(requestKey),
          ...failure,
        });
      }
    }

    void load();
    return () => {
      controller.abort();
      trendControllerRef.current?.abort();
    };
  }, [normalizedTsCode, requestKey, tradeDate, loadPageInit, loadDailyKline]);

  const retry = useCallback(() => setRetryToken((value) => value + 1), []);
  const retryTrend = useCallback(() => {
    const endDate = state.viewModel?.asOfTradeDate;
    if (!endDate || normalizedTsCode !== "000001.SH") return;
    const requestId = requestIdRef.current;
    trendControllerRef.current?.abort();
    const controller = new AbortController();
    trendControllerRef.current = controller;
    setState((current) => ({
      ...current,
      partialReasons: current.pagePartialReasons,
      phase: current.basePhase,
      trend: null,
      trendPhase: "loading",
    }));
    void requestTrend(endDate, controller.signal)
      .then((trend) => commitTrendSuccess(setState, requestIdRef, requestId, trend))
      .catch((error: unknown) => {
        if (!controller.signal.aborted) commitTrendFailure(setState, requestIdRef, requestId, error);
      });
  }, [normalizedTsCode, state.viewModel?.asOfTradeDate]);

  const visibleState = state.requestKey === requestKey ? state : createInitialState(requestKey);
  const history = useIndexDailyHistory(visibleState.historySeed, dailyActive, loadDailyKline, loadNineTurn);
  return { ...visibleState, history, retry, retryTrend };
}

function createInitialState(requestKey: string): IndexDetailControllerSnapshot {
  return {
    basePhase: "ready",
    errorCode: "",
    errorMessage: "",
    historySeed: null,
    pagePartialReasons: [],
    partialReasons: [],
    phase: "loading",
    requestKey,
    trend: null,
    trendPhase: "unavailable",
    viewModel: null,
  };
}

async function requestTrend(endDate: string, signal: AbortSignal): Promise<TrendChannelViewModel> {
  const response = await fetchTrendChannel({ endDate, limit: DAILY_CHART_PAGE_SIZE }, { signal });
  return buildTrendChannelViewModel(response);
}

function commitTrendSuccess(
  setState: (updater: (current: IndexDetailControllerSnapshot) => IndexDetailControllerSnapshot) => void,
  requestIdRef: { current: number },
  requestId: number,
  trend: TrendChannelViewModel,
) {
  if (requestIdRef.current !== requestId) return;
  setState((current) => ({
    ...current,
    partialReasons: current.pagePartialReasons,
    phase: current.viewModel ? current.basePhase : current.phase,
    trend,
    trendPhase: "ready",
  }));
}

function commitTrendFailure(
  setState: (updater: (current: IndexDetailControllerSnapshot) => IndexDetailControllerSnapshot) => void,
  requestIdRef: { current: number },
  requestId: number,
  _error: unknown,
) {
  if (requestIdRef.current !== requestId) return;
  setState((current) => ({
    ...current,
    partialReasons: mergeReasons(current.pagePartialReasons, ["趋势通道"]),
    phase: current.viewModel ? "partial" : current.phase,
    trend: null,
    trendPhase: "error",
  }));
}

function resolvePageFailure(error: unknown): Pick<IndexDetailControllerSnapshot, "errorCode" | "errorMessage" | "phase"> {
  if (error instanceof IndexDetailApiError) {
    if (error.status === 403) return { errorCode: error.code, errorMessage: error.message, phase: "forbidden" };
    if (error.status === 400 || error.status === 404) {
      return { errorCode: error.code, errorMessage: error.message, phase: "notFound" };
    }
    return { errorCode: error.code, errorMessage: error.message, phase: "error" };
  }
  return {
    errorCode: "ID_QUERY_FAILED",
    errorMessage: error instanceof Error ? error.message : "指数详情数据加载失败",
    phase: "error",
  };
}

function isCurrent(requestIdRef: { current: number }, requestId: number, signal: AbortSignal): boolean {
  return requestIdRef.current === requestId && !signal.aborted;
}

function mergeReasons(left: string[], right: string[]): string[] {
  return [...new Set([...left, ...right])];
}
