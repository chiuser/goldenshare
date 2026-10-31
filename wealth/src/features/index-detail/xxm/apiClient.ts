import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { indexDetailRequests } from "../api/indexDetailRequestScheduler";
import { decodeXxmResponse } from "./adapter";
import type { DecodeXxmDebug } from "../debug/types";
import type { XxmPeriod, XxmRequestResult } from "./types";
export const XXM_TIMEOUT_MS = 5000;
export function checkRequest(signal: AbortSignal, deadline: number) {
    if (signal.aborted)
        throw new DOMException("请求已取消", "AbortError");
    if (performance.now() >= deadline)
        throw new Error("顶底识别加载超时，请重试");
}
interface Params {
    tsCode: string;
    period: XxmPeriod;
    startDate: string;
    endDate: string;
    limit: number;
    debug?: 1;
    decodeDebug?: DecodeXxmDebug;
}
export function fetchXxm(params: Params, signal: AbortSignal): Promise<XxmRequestResult> {
    return indexDetailRequests.run("xxm", () => sendXxm(params, signal, performance.now() + XXM_TIMEOUT_MS), signal);
}
async function sendXxm(params: Params, signal: AbortSignal, deadline: number): Promise<XxmRequestResult> {
    const minute = params.period !== "day", endpoint = minute ? "minute-xxm-signals" : "xxm-signals";
    const url = new URL(`/api/v1/wealth/market/index-detail/${endpoint}`, window.location.origin);
    url.search = new URLSearchParams({ tsCode: params.tsCode, startDate: params.startDate, endDate: params.endDate, limit: String(params.limit), ...(minute ? { freq: params.period.slice(1) } : { period: "day" }), ...(params.debug ? { debug: "1" } : {}) }).toString();
    const controller = new AbortController();
    const abort = () => controller.abort(signal.reason);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted)
        abort();
    const check = () => { checkRequest(signal, deadline); if (controller.signal.aborted)
        throw new Error("顶底识别加载超时，请重试"); };
    const timer = setTimeout(() => controller.abort(), Math.max(0, deadline - performance.now()));
    try {
        check();
        const http = await wealthFetch(url, { signal: controller.signal });
        check();
        if (!http.ok) {
            const body = await http.json().catch(() => null) as {
                message?: string;
            } | null;
            check();
            throw new Error(body?.message || "顶底识别加载失败，请重试");
        }
        const raw: unknown = await http.json();
        check();
        const response = decodeXxmResponse(raw, { tsCode: params.tsCode, period: params.period, debug: params.debug ?? 0, decodeDebug: params.decodeDebug, check });
        check();
        return { response, deadline };
    }
    catch (error) {
        checkRequest(signal, deadline);
        if (controller.signal.aborted)
            throw new Error("顶底识别加载超时，请重试");
        if (error instanceof TypeError)
            throw new Error("顶底识别暂时无法连接，请重试");
        throw error;
    }
    finally {
        clearTimeout(timer);
        signal.removeEventListener("abort", abort);
    }
}
