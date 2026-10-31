import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { DetailChartPoint } from "../../../shared/charts/detail-workspace/detailChartTypes";
import { buildXxmViewModel } from "./adapter";
import { fetchXxm, checkRequest, XXM_TIMEOUT_MS } from "./apiClient";
import { XxmMacdPrimitive } from "./XxmMacdPrimitive";
import type { XxmLayerState, XxmPeriod, XxmResponse, XxmDebugResponse } from "./types";

import type { DecodeXxmDebug } from "../debug/types";
import { XXM_ALGORITHM_VERSION, XXM_SPEC_HASH } from "./types";

const unsupported: XxmLayerState = { requestKey: "", phase: "unsupported", data: null, errorMessage: "" };

export function useIndexXxmLayer({ tsCode, period, points, indicatorVersion = null, indicatorsPending = false, enabled, debug, decodeDebug }: {
  tsCode: string; period: string; points: DetailChartPoint[]; indicatorVersion?: number | null; indicatorsPending?: boolean; enabled: boolean; debug: 0|1; decodeDebug?: DecodeXxmDebug;
}) {
  const supported = enabled && import.meta.env.DEV && (debug === 0 || !!decodeDebug) && tsCode === "000001.SH" && ["day", "m60", "m90", "m120"].includes(period);
  const ready = points.length > 0 && points.every(point => [point.close, point.dif, point.dea, point.macd].every(Number.isFinite));
  const requestKey = `${XXM_ALGORITHM_VERSION}|${XXM_SPEC_HASH}|${debug}|${indicatorVersion}|${tsCode}|${period}|${points[0]?.fullDate ?? ""}|${points.at(-1)?.fullDate ?? ""}|${points.length}`;
  const [state, setState] = useState<XxmLayerState>(unsupported);
  const [retryToken, setRetryToken] = useState(0);
  const currentRequest = useRef(0);
  const cache = useRef<{ key: string; version: string; response: XxmResponse | XxmDebugResponse } | null>(null);
  const version = useRef("");
  const primitive = useMemo(() => supported ? new XxmMacdPrimitive() : null, [supported, tsCode, period]);
  const retry = useCallback(() => { if (!supported) return; cache.current = null; setRetryToken(token => token + 1); }, [supported]);

  useEffect(() => {
    const identity = ++currentRequest.current;
    if (!supported) { cache.current = null; setState(unsupported); return; }
    if (!ready) {
      setState({ requestKey, phase: indicatorsPending ? "loading" : "error", data: null,
        errorMessage: indicatorsPending ? "" : "原始 MACD 数据缺失，暂不能计算顶底识别。" });
      return;
    }
    const options = { tsCode, period: period as XxmPeriod, startDate: points[0]!.fullDate.slice(0, 10),
      endDate: points.at(-1)!.fullDate.slice(0, 10), limit: points.length, debug: debug === 1 ? 1 as const : undefined, decodeDebug };
    const controller = new AbortController();
    const apply = (response: XxmResponse | XxmDebugResponse, deadline: number) => {
      const check = () => { checkRequest(controller.signal, deadline); if (currentRequest.current !== identity) throw new DOMException("请求已过期", "AbortError"); };
      check();
      const data = buildXxmViewModel(response, points, options.period, tsCode, indicatorVersion, check);
      check();
      version.current = `${response.algorithmVersion}|${response.specHash}`;
      cache.current = { key: requestKey, version: version.current, response };
      setState({ requestKey, phase: response.dataStatus.status.toLowerCase() as "ready" | "delayed" | "empty", data, errorMessage: "" });
    };
    if (cache.current?.key === requestKey && cache.current.version === version.current) {
      try { apply(cache.current.response, performance.now() + XXM_TIMEOUT_MS); return; } catch { cache.current = null; }
    }
    setState({ requestKey, phase: "loading", data: null, errorMessage: "" });
    fetchXxm(options, controller.signal).then(({ response, deadline }) => {
      if (!controller.signal.aborted && currentRequest.current === identity) apply(response, deadline);
    }).catch(error => {
      if (controller.signal.aborted || currentRequest.current !== identity) return;
      setState({ requestKey, phase: "error", data: null, errorMessage: error instanceof Error ? error.message : "顶底识别加载失败" });
    });
    return () => controller.abort();
  }, [supported, ready, indicatorsPending, requestKey, tsCode, period, points, indicatorVersion, retryToken, debug, decodeDebug]);

  const current = supported ? state.requestKey === requestKey ? state : { ...unsupported, requestKey, phase: "loading" as const } : unsupported;
  useEffect(() => { primitive?.setMarkers(current.data?.markers ?? []); }, [primitive, current.data]);
  const macdPrimitives = useMemo(() => primitive ? [primitive] : [], [supported, primitive]);
  return { ...current, retry, macdPrimitives };
}
