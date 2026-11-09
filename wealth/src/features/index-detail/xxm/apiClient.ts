import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { indexDetailRequests } from "../api/indexDetailRequestScheduler";
import { decodeXxmResponse, type XxmDecodeOptions } from "./adapter";
import type { XxmHistoryResponse, XxmPeriod, XxmRequestResult } from "./types";
export const XXM_TIMEOUT_MS = 5000;
export function checkRequest(signal: AbortSignal, deadline: number) {
    if (signal.aborted)
        throw new DOMException("请求已取消", "AbortError");
    if (performance.now() >= deadline)
        throw new Error("顶底识别加载超时，请重试");
}
export interface XxmRequestParams {
    tsCode: string;
    period: XxmPeriod;
    startDate: string;
    endDate: string;
    limit: number;
}
export function fetchXxm(params: XxmRequestParams, signal: AbortSignal): Promise<XxmRequestResult> {
    return indexDetailRequests.run("xxm", () => sendXxm(params, signal, performance.now() + XXM_TIMEOUT_MS, "", decodeXxmResponse), signal);
}
export async function sendXxm(params: XxmRequestParams, signal: AbortSignal, deadline: number,
    prefix: string, decode: (raw: unknown, options: XxmDecodeOptions) => XxmHistoryResponse): Promise<XxmRequestResult> {
    const minute = params.period !== "day", endpoint = minute ? "minute-xxm-signals" : "xxm-signals";
    const url = new URL(`/api/v1/wealth/market/index-detail/${prefix}${endpoint}`, window.location.origin);
    url.search = new URLSearchParams({ tsCode: params.tsCode, startDate: params.startDate, endDate: params.endDate, limit: String(params.limit), ...(minute ? { freq: params.period.slice(1) } : { period: "day" }) }).toString();
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
        const response = decode(raw, { tsCode: params.tsCode, period: params.period, check });
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
