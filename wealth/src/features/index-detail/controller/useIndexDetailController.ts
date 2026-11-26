import type { IndexKlineLoader } from "../api/indexDetailApiClient";
import { useCallback, useEffect, useRef, useState } from "react";

import type { NineTurnMarkerDto } from "../../nine-turn/api/nineTurnApiTypes";
import {
  fetchIndexDetailKline,
  fetchIndexDetailPageInit,
  IndexDetailApiError,
} from "../api/indexDetailApiClient";
import { loadIndexNineTurnSeries } from "../api/indexNineTurnLoader";
import {
  buildEmptyIndexDetailViewModel,
  buildIndexDetailViewModel, buildIndexDailyTrendChannelPoints,
} from "../api/indexDetailViewModelAdapter";
import { DAILY_CHART_PAGE_SIZE } from "../../../shared/charts/dailyChartRequestLimits";
import { readIndexDailyCursor, useIndexDailyHistory, type IndexDailyHistory, type IndexDailyHistorySeed } from "./useIndexDailyHistory";
import {
  collectIndexPartialReasons,
  normalizeIndexTsCode,
  resolveIndexDataPagePhase,
} from "../model/indexDetailState";
import type {
  IndexDataPagePhase,
  IndexDetailViewModel,
  IndexPagePhase,
  TrendChannelPoint,
} from "../model/indexDetailTypes";

interface IndexDetailControllerSnapshot {
  basePhase: IndexDataPagePhase;
  dailyNineTurnMarkers: NineTurnMarkerDto[] | null;
  errorCode: string;
  errorMessage: string;
  pagePartialReasons: string[];
  partialReasons: string[];
  phase: IndexPagePhase;
  requestKey: string;
  historySeed: IndexDailyHistorySeed | null;
  dailyTrendPoints: TrendChannelPoint[];
  viewModel: IndexDetailViewModel | null;
}

export interface IndexDetailControllerState extends IndexDetailControllerSnapshot {
  history: IndexDailyHistory;
  retry: () => void;
}

export function useIndexDetailController(tsCode: string, tradeDate: string | undefined, dailyActive = true,
    loadPageInit = fetchIndexDetailPageInit, loadDailyKline: IndexKlineLoader = fetchIndexDetailKline, loadNineTurn = loadIndexNineTurnSeries): IndexDetailControllerState {
  const normalizedTsCode = normalizeIndexTsCode(tsCode);
  const [retryToken, setRetryToken] = useState(0);
  const requestKey = `${normalizedTsCode}|${tradeDate ?? ""}|${retryToken}`;
  const [state, setState] = useState<IndexDetailControllerSnapshot>(() => createInitialState(requestKey));
  const requestIdRef = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    const requestId = ++requestIdRef.current;
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

        const kline = await loadDailyKline(
          { tsCode: normalizedTsCode, period: "day", endDate: pageInit.asOfTradeDate, limit: DAILY_CHART_PAGE_SIZE },
          { signal: controller.signal },
        );
        if (!isCurrent(requestIdRef, requestId, controller.signal)) return;
        if (kline.indexRef.tsCode !== normalizedTsCode) throw new Error("指数K线返回的代码与请求不一致");
        const markers = kline.period === "day" ? kline.nineTurnMarkers : undefined;
        if ("nineTurnMarkers" in kline && !Array.isArray(markers)) {
          throw new Error("指数日线回包缺少有效的九转标记");
        }
        const supportsDailyHistory = normalizedTsCode === "000001.SH" || "nextEndDate" in kline.meta;
        const nextEndDate = supportsDailyHistory
          ? readIndexDailyCursor(kline, normalizedTsCode, pageInit.asOfTradeDate)
          : null;
        if (kline.dataStatus.status === "EMPTY" || kline.bars.length === 0) {
          setState({
            ...createInitialState(requestKey),
            phase: "empty",
            viewModel: buildEmptyIndexDetailViewModel(pageInit),
          });
          return;
        }

        const basePhase = resolveIndexDataPagePhase(pageInit, kline);
        const pagePartialReasons = collectIndexPartialReasons(pageInit, kline);
        const dailyTrendPoints = buildIndexDailyTrendChannelPoints(kline);
        const viewModel = buildIndexDetailViewModel(pageInit, kline);
        setState((current) => {
          return {
            ...current,
            basePhase,
            dailyNineTurnMarkers: markers ?? null, dailyTrendPoints,
            errorCode: "",
            errorMessage: "",
            pagePartialReasons,
            partialReasons: pagePartialReasons,
            phase: basePhase,
            historySeed: supportsDailyHistory ? { viewModel, nextEndDate, embeddedNineTurn: markers !== undefined, dailyTrendPoints } : null,
            viewModel,
          };
        });
      } catch (error) {
        if (!isCurrent(requestIdRef, requestId, controller.signal)) return;
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
    };
  }, [normalizedTsCode, requestKey, tradeDate, loadPageInit, loadDailyKline]);

  const retry = useCallback(() => setRetryToken((value) => value + 1), []);
  const visibleState = state.requestKey === requestKey ? state : createInitialState(requestKey);
  const history = useIndexDailyHistory(visibleState.historySeed, dailyActive, loadDailyKline, loadNineTurn);
  return { ...visibleState, history, retry };
}

function createInitialState(requestKey: string): IndexDetailControllerSnapshot {
  return {
    basePhase: "ready",
    dailyNineTurnMarkers: null,
    errorCode: "",
    errorMessage: "",
    historySeed: null,
    pagePartialReasons: [],
    partialReasons: [],
    phase: "loading",
    requestKey,
    dailyTrendPoints: [],
    viewModel: null,
  };
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
