import { useCallback, useEffect, useRef, useState } from "react";

import { fetchIndexDetailMinutes, IndexDetailApiError } from "../api/indexDetailApiClient";
import {
  buildIndexMinuteBarsOnlyViewModel,
  buildIndexMinuteChartViewModel,
} from "../api/indexMinuteViewModelAdapter";
import type { IndexDetailMinuteFrequency } from "../api/indexDetailApiTypes";
import type { IndexMinuteSeriesState, IndexPeriodKey } from "../model/indexDetailTypes";

const idleState: IndexMinuteSeriesState = { data: null, errorMessage: "", phase: "idle" };

export function useIndexMinuteSeries({
  activePeriod,
  enabled,
  endDate,
  tsCode,
}: {
  activePeriod: IndexPeriodKey;
  enabled: boolean;
  endDate: string | null;
  tsCode: string;
}): IndexMinuteSeriesState & { retry: () => void } {
  const [state, setState] = useState<IndexMinuteSeriesState>(idleState);
  const [retryToken, setRetryToken] = useState(0);
  const cacheRef = useRef(new Map<string, IndexMinuteSeriesState>());
  const requestIdRef = useRef(0);

  useEffect(() => {
    const freq = minuteFrequencyFromPeriod(activePeriod);
    if (!import.meta.env.DEV || !enabled || freq === null || endDate === null) {
      requestIdRef.current += 1;
      setState(idleState);
      return;
    }
    const cacheKey = `${tsCode}|${freq}|${endDate}`;
    const cached = cacheRef.current.get(cacheKey);
    if (cached) {
      requestIdRef.current += 1;
      setState(cached);
      return;
    }

    const controller = new AbortController();
    const requestId = ++requestIdRef.current;
    setState({ data: null, errorMessage: "", phase: "loading" });
    fetchIndexDetailMinutes(
      { tsCode, freq, endDate, limit: 500 },
      { signal: controller.signal },
    ).then((response) => {
      if (controller.signal.aborted || requestIdRef.current !== requestId) return;
      if (response.bars.length === 0 || response.dataStatus.status === "EMPTY") {
        const empty: IndexMinuteSeriesState = {
          data: null,
          errorMessage: response.dataStatus.message ?? "当前分钟数据源暂不覆盖该指数。",
          phase: "empty",
        };
        cacheRef.current.set(cacheKey, empty);
        setState(empty);
        return;
      }
      let data;
      let indicatorPartial = false;
      try {
        data = buildIndexMinuteChartViewModel(response);
      } catch {
        data = buildIndexMinuteBarsOnlyViewModel(response);
        indicatorPartial = true;
      }
      const ready: IndexMinuteSeriesState = {
        data,
        errorMessage: indicatorPartial ? "模拟指标生成失败，分钟 K 线仍可使用。" : response.dataStatus.message ?? "",
        phase: indicatorPartial ? "partial" : response.dataStatus.status === "DELAYED" ? "delayed" : "ready",
      };
      cacheRef.current.set(cacheKey, ready);
      setState(ready);
    }).catch((error: unknown) => {
      if (controller.signal.aborted || requestIdRef.current !== requestId) return;
      setState({
        data: null,
        errorMessage: resolveMinuteError(error),
        phase: "error",
      });
    });
    return () => controller.abort();
  }, [activePeriod, enabled, endDate, retryToken, tsCode]);

  const retry = useCallback(() => setRetryToken((value) => value + 1), []);
  return { ...state, retry };
}

export function minuteFrequencyFromPeriod(period: IndexPeriodKey): IndexDetailMinuteFrequency | null {
  const match = /^m(1|5|15|30|60|90|120)$/.exec(period);
  return match ? Number(match[1]) as IndexDetailMinuteFrequency : null;
}

function resolveMinuteError(error: unknown): string {
  if (error instanceof IndexDetailApiError) return error.message;
  return error instanceof Error ? error.message : "指数分钟数据加载失败";
}
