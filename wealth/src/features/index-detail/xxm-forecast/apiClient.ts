import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { indexDetailRequests } from "../api/indexDetailRequestScheduler";
import { checkRequest, XXM_TIMEOUT_MS } from "../xxm/apiClient";
import { adaptForecast, type ForecastDecodeOptions } from "./adapter";
import type { ForecastPeriod, ForecastRequestResult, ForecastResponse, ForecastDebugResponse } from "./types";
export function fetchForecast(tsCode: string, period: ForecastPeriod, asOf: string | undefined,
    signal: AbortSignal): Promise<ForecastRequestResult> {
    return indexDetailRequests.run("forecast", () => sendForecast(tsCode, period, asOf, signal,
        performance.now() + XXM_TIMEOUT_MS, "", adaptForecast), signal);
}
export async function sendForecast(tsCode: string, period: ForecastPeriod, asOf: string | undefined, signal: AbortSignal,
    deadline: number, prefix: string, decode: (raw: unknown, options: ForecastDecodeOptions) => ForecastResponse | ForecastDebugResponse): Promise<ForecastRequestResult> {
    const params = new URLSearchParams({ tsCode, period });
    if (asOf)
        params.set("asOf", asOf);
    const controller = new AbortController();
    const abort = () => controller.abort(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted)
        abort();
    const check = () => { checkRequest(signal, deadline); if (controller.signal.aborted)
        throw new Error("关键点预判加载超时，请重试"); };
    const timer = setTimeout(() => controller.abort(), Math.max(0, deadline - performance.now()));
    try {
        check();
        const http = await wealthFetch(`/api/v1/wealth/market/index-detail/${prefix}xxm-key-point-forecast?${params}`, { signal: controller.signal });
        check();
        if (!http.ok) {
            const body = await http.json().catch(() => null) as {
                message?: string;
            } | null;
            check();
            throw new Error(body?.message || "关键点预判加载失败，请重试");
        }
        const raw: unknown = await http.json();
        check();
        const response = decode(raw, { tsCode, period, asOf, check });
        check();
        return { response, deadline };
    }
    catch (error) {
        checkRequest(signal, deadline);
        if (controller.signal.aborted)
            throw new Error("关键点预判加载超时，请重试");
        if (error instanceof TypeError)
            throw new Error("关键点预判暂时无法连接，请重试");
        throw error;
    }
    finally {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
    }
}
