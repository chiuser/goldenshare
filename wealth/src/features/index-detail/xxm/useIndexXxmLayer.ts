import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { buildXxmViewModel } from "./adapter";
import { fetchXxm } from "./apiClient";
import { XxmMacdPrimitive } from "./XxmMacdPrimitive";
import type { XxmLayerState, XxmPeriod, XxmResponse } from "./types";

const unsupported: XxmLayerState = { requestKey: "", phase: "unsupported", data: null, errorMessage: "" };

export function useIndexXxmLayer({ tsCode, period, points, indicatorVersion = null, indicatorsPending = false }: {
  tsCode: string; period: string; points: DetailChartPoint[]; indicatorVersion?: number | null; indicatorsPending?: boolean;
}) {
  const supported = tsCode === "000001.SH" && ["day", "m60", "m90", "m120"].includes(period)
    && (period === "day" || import.meta.env.DEV);
  const ready = points.length > 0 && points.every(point => [point.close, point.dif, point.dea, point.macd].every(Number.isFinite));
  const requestKey = `${tsCode}|${period}|${points[0]?.fullDate ?? ""}|${points.at(-1)?.fullDate ?? ""}|${points.length}`;
  const [state, setState] = useState<XxmLayerState>(unsupported);
  const [retryToken, setRetryToken] = useState(0);
  const currentRequest = useRef(0);
  const cache = useRef<{ key: string; version: string; response: XxmResponse } | null>(null);
  const version = useRef("");
  const primitive = useMemo(() => new XxmMacdPrimitive(), [tsCode, period]);
  const retry = useCallback(() => { cache.current = null; setRetryToken(token => token + 1); }, []);

  useEffect(() => {
    const identity = ++currentRequest.current;
    if (!supported) { setState(unsupported); return; }
    if (!ready) {
      setState({ requestKey, phase: indicatorsPending ? "loading" : "error", data: null,
        errorMessage: indicatorsPending ? "" : "原始 MACD 数据缺失，暂不能计算研究指标。" });
      return;
    }
    const options = { tsCode, period: period as XxmPeriod, startDate: points[0]!.fullDate.slice(0, 10),
      endDate: points.at(-1)!.fullDate.slice(0, 10), limit: points.length };
    const apply = (response: XxmResponse) => {
      const data = buildXxmViewModel(response, points, options.period, tsCode, indicatorVersion);
      version.current = `${response.algorithmVersion}|${response.specHash}`;
      cache.current = { key: requestKey, version: version.current, response };
      setState({ requestKey, phase: response.dataStatus.status.toLowerCase() as "ready" | "delayed" | "empty", data, errorMessage: "" });
    };
    if (cache.current?.key === requestKey && cache.current.version === version.current) {
      try { apply(cache.current.response); return; } catch { cache.current = null; }
    }
    const controller = new AbortController();
    setState({ requestKey, phase: "loading", data: null, errorMessage: "" });
    fetchXxm(options, controller.signal).then(response => {
      if (!controller.signal.aborted && currentRequest.current === identity) apply(response);
    }).catch(error => {
      if (controller.signal.aborted || currentRequest.current !== identity) return;
      setState({ requestKey, phase: "error", data: null, errorMessage: error instanceof Error ? error.message : "研究指标加载失败" });
    });
    return () => controller.abort();
  }, [supported, ready, indicatorsPending, requestKey, tsCode, period, points, indicatorVersion, retryToken]);

  const current = supported ? state.requestKey === requestKey ? state : { ...unsupported, requestKey, phase: "loading" as const } : unsupported;
  useEffect(() => { primitive.setMarkers(current.data?.markers ?? []); }, [primitive, current.data]);
  const macdPrimitives = useMemo(() => supported ? [primitive] : [], [supported, primitive]);
  return { ...current, retry, macdPrimitives };
}
