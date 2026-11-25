import type { IndexDetailRequestScheduler } from "../api/indexDetailRequestScheduler";
import { useCallback, useEffect, useRef, useState } from "react";

import type { NineTurnPeriod, NineTurnSeriesDto } from "../../nine-turn/api/nineTurnApiTypes";
import { adaptNineTurnSeries } from "../../nine-turn/model/nineTurnAdapter";
import type { NineTurnLayerViewModel } from "../../nine-turn/model/nineTurnTypes";
import {
  fetchIndexDetailMinuteIndicators,
  fetchIndexDetailMinutes,
  IndexDetailApiError,
} from "../api/indexDetailApiClient";
import {
  buildIndexMinuteBarsOnlyViewModel,
  buildIndexMinuteChartViewModel,
} from "../api/indexMinuteViewModelAdapter";
import type { IndexDetailMinuteFrequency } from "../api/indexDetailApiTypes";
import type {
  IndexMinuteChartViewModel,
  IndexMinuteSeriesState,
  IndexPeriodKey,
} from "../model/indexDetailTypes";

const idleState: IndexMinuteSeriesState = { data: null, errorMessage: "", phase: "idle" };

interface CachedMinuteWindow {
  series: IndexMinuteSeriesState | null;
  nineTurn: NineTurnLayerViewModel | null;
}

export function useIndexMinuteSeries({
  activePeriod,
  enabled,
  endDate,
  requests,
  tsCode,
}: {
  activePeriod: IndexPeriodKey;
  enabled: boolean;
  endDate: string | null;
  requests?: IndexDetailRequestScheduler;
  tsCode: string;
}): IndexMinuteSeriesState & {
  retry: () => void;
  nineTurnFor: (period: Exclude<NineTurnPeriod, "day">) => NineTurnLayerViewModel | null;
} {
  const [state, setState] = useState<IndexMinuteSeriesState>(idleState);
  const [retryToken, setRetryToken] = useState(0);
  const cacheRef = useRef(new Map<string, CachedMinuteWindow>());
  const requestIdRef = useRef(0);

  useEffect(() => {
    const freq = minuteFrequencyFromPeriod(activePeriod);
    if (!import.meta.env.DEV || !enabled || freq === null || endDate === null) {
      requestIdRef.current += 1;
      setState(idleState);
      return;
    }
    const cacheKey = `${tsCode}|${freq}|${endDate}`;
    const cached = cacheRef.current.get(cacheKey)?.series;
    if (cached) {
      requestIdRef.current += 1;
      setState(cached);
      return;
    }

    const controller = new AbortController();
    const requestId = ++requestIdRef.current;
    setState({ data: null, errorMessage: "", phase: "loading" });
    const request = { tsCode, freq, endDate, limit: 500 } as const;
    const indicatorsRequest = settle(
      fetchIndexDetailMinuteIndicators(request, { signal: controller.signal }, requests),
    );
    fetchIndexDetailMinutes(request, { signal: controller.signal }, requests).then((response) => {
      if (controller.signal.aborted || requestIdRef.current !== requestId) return;
      const nineTurn = freq === 1 ? null : adaptMinuteNineTurn(response.nineTurn, freq, tsCode);
      if (response.bars.length === 0 || response.dataStatus.status === "EMPTY") {
        const empty: IndexMinuteSeriesState = {
          data: null,
          errorMessage: response.dataStatus.message ?? "当前分钟数据源暂不覆盖该指数。",
          phase: "empty",
        };
        cacheRef.current.set(cacheKey, { series: empty, nineTurn });
        setState(empty);
        return;
      }
      let data: IndexMinuteChartViewModel;
      try {
        data = buildIndexMinuteBarsOnlyViewModel(response);
      } catch (error) {
        setState({ data: null, errorMessage: resolveMinuteError(error), phase: "error" });
        return;
      }
      cacheRef.current.set(cacheKey, { series: null, nineTurn });
      setState({
        data,
        errorMessage: response.dataStatus.message ?? "",
        phase: response.dataStatus.status === "DELAYED" ? "delayed" : "loading",
      });

      indicatorsRequest.then((indicatorsResult) => {
        if (controller.signal.aborted || requestIdRef.current !== requestId) return;
        let indicatorPartial = false;
        let indicatorMessage = "";
        if (
          indicatorsResult.status === "fulfilled"
          && indicatorsResult.value.items.length > 0
          && indicatorsResult.value.dataStatus.status !== "EMPTY"
        ) {
          try {
            data = buildIndexMinuteChartViewModel(response, indicatorsResult.value);
            indicatorMessage = indicatorsResult.value.dataStatus.message ?? "";
          } catch {
            indicatorPartial = true;
            indicatorMessage = "分钟技术指标与 K 线无法对齐，分钟 K 线仍可使用。";
          }
        } else {
          indicatorPartial = true;
          indicatorMessage = resolveIndicatorMessage(indicatorsResult);
        }
        const ready: IndexMinuteSeriesState = {
          data,
          errorMessage: indicatorPartial
            ? indicatorMessage
            : response.dataStatus.message ?? indicatorMessage,
          phase: indicatorPartial
            ? "partial"
            : response.dataStatus.status === "DELAYED"
              || (indicatorsResult.status === "fulfilled" && indicatorsResult.value.dataStatus.status === "DELAYED")
              ? "delayed"
              : "ready",
        };
        cacheRef.current.set(cacheKey, { series: ready, nineTurn });
        setState(ready);
      });
    }).catch((error: unknown) => {
      if (controller.signal.aborted || requestIdRef.current !== requestId) return;
      controller.abort();
      setState({ data: null, errorMessage: resolveMinuteError(error), phase: "error" });
    });
    return () => controller.abort();
  }, [activePeriod, enabled, endDate, requests, retryToken, tsCode]);

  const retry = useCallback(() => setRetryToken((value) => value + 1), []);
  const nineTurnFor = useCallback((period: Exclude<NineTurnPeriod, "day">) =>
    cacheRef.current.get(`${tsCode}|${period}|${endDate}`)?.nineTurn ?? null, [tsCode, endDate]);
  return { ...state, retry, nineTurnFor };
}

function adaptMinuteNineTurn(
  series: NineTurnSeriesDto | null,
  freq: Exclude<IndexDetailMinuteFrequency, 1>,
  tsCode: string,
): NineTurnLayerViewModel {
  if (!series) throw new Error("指数分钟行情回包缺少九转序列");
  return adaptNineTurnSeries(series, { period: String(freq) as Exclude<NineTurnPeriod, "day">, subjectType: "index", tsCode });
}

export function minuteFrequencyFromPeriod(period: IndexPeriodKey): IndexDetailMinuteFrequency | null {
  const match = /^m(1|5|15|30|60|90|120)$/.exec(period);
  return match ? Number(match[1]) as IndexDetailMinuteFrequency : null;
}

function resolveMinuteError(error: unknown): string {
  if (error instanceof IndexDetailApiError) return error.message;
  return error instanceof Error ? error.message : "指数分钟数据加载失败";
}

function resolveIndicatorMessage(
  result: PromiseSettledResult<Awaited<ReturnType<typeof fetchIndexDetailMinuteIndicators>>>,
): string {
  if (result.status === "fulfilled") {
    return result.value.dataStatus.message ?? "分钟技术指标暂不可用，分钟 K 线仍可使用。";
  }
  return "分钟技术指标加载失败，分钟 K 线仍可使用。";
}

function settle<T>(promise: Promise<T>): Promise<PromiseSettledResult<T>> {
  return promise.then(
    (value) => ({ status: "fulfilled", value }),
    (reason: unknown) => ({ status: "rejected", reason }),
  );
}
