import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { indexDetailRequests } from "../api/indexDetailRequestScheduler";
import { checkRequest, XXM_TIMEOUT_MS } from "../xxm/apiClient";
import { adaptForecast } from "./adapter";
import type { ForecastPeriod, ForecastRequestResult } from "./types";
import type { DecodeForecastDebug } from "../debug/types";
export function fetchForecast(period: ForecastPeriod, asOf: string | undefined, signal: AbortSignal, options: {
    debug?: 1;
    decodeDebug?: DecodeForecastDebug;
} = {}): Promise<ForecastRequestResult> {
    return indexDetailRequests.run("forecast", () => sendForecast(period, asOf, signal, options, performance.now() + XXM_TIMEOUT_MS), signal);
}
async function sendForecast(period: ForecastPeriod, asOf: string | undefined, signal: AbortSignal, options: {
    debug?: 1;
    decodeDebug?: DecodeForecastDebug;
}, deadline: number): Promise<ForecastRequestResult> {
    const params = new URLSearchParams({ tsCode: "000001.SH", period });
    if (asOf)
        params.set("asOf", asOf);
    if (options.debug)
        params.set("debug", "1");
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
        const http = await wealthFetch(`/api/v1/wealth/market/index-detail/xxm-key-point-forecast?${params}`, { signal: controller.signal });
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
        const response = adaptForecast(raw, { period, asOf, debug: options.debug ?? 0, decodeDebug: options.decodeDebug, check });
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
