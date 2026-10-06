import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { clientPolicy } from "./clientPolicy";
import type { Companies, Conditions, Context, Files, History, ModuleCard, Preview, PreviewRequest, QueryResult, RecheckKind, ResultFilter, Task } from "./contracts";
const ROOT = "/api/v1/wealth/data-center";
const ANN = `${ROOT}/announcements`;
export class DataCenterApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) { super(message); }
}
/** Approved 5 second observer budget includes response body parsing. No automatic command retries. */
export async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) controller.abort();
  const timer = window.setTimeout(cancel, clientPolicy.requestSeconds * 1000);
  try {
    const response = await wealthFetch(path, { ...init, signal: controller.signal });
    const body = await response.json();
    if (!response.ok) {
      const detail = body.detail ?? body.error ?? body;
      throw new DataCenterApiError(response.status, typeof detail.code === "string" ? detail.code : "",
        typeof detail.message === "string" ? detail.message : "请求暂不可获取，请重新读取");
    }
    return body as T;
  } catch (error) {
    if (controller.signal.aborted && !signal?.aborted) throw new Error("请求超时，连接状态暂不可获取");
    throw error;
  } finally { window.clearTimeout(timer); signal?.removeEventListener("abort", cancel); }
}
const post = <T>(path: string, body: unknown, key?: string, signal?: AbortSignal) => request<T>(path,
  { method: "POST", headers: { "Content-Type": "application/json", ...(key ? { "Idempotency-Key": key } : {}) }, body: JSON.stringify(body) }, signal);
const url = (path: string, params: Record<string, string | null | undefined>) => {
  const search = new URLSearchParams(); Object.entries(params).forEach(([k, v]) => { if (v != null) search.set(k, v); });
  return `${path}?${search}`;
};
export const dataCenterApi = {
  modules: (s?: AbortSignal) => request<{ modules: ModuleCard[] }>(`${ROOT}/modules`, {}, s),
  context: (s?: AbortSignal) => request<Context>(`${ANN}/context`, {}, s),
  companies: (keyword: string, dates: Pick<Conditions, "startDate" | "endDate">, s?: AbortSignal) => request<Companies>(url(`${ANN}/companies`, { keyword, startDate: dates.startDate, endDate: dates.endDate }), {}, s),
  createQuery: (conditions: Conditions, s?: AbortSignal) => post<QueryResult>(`${ANN}/queries`, conditions, undefined, s),
  query: (id: string, page: number, s?: AbortSignal) => request<QueryResult>(url(`${ANN}/queries/${encodeURIComponent(id)}`, { page: String(page) }), {}, s),
  createPreview: (body: PreviewRequest, s?: AbortSignal) => post<Preview>(`${ANN}/previews`, body, undefined, s),
  preview: (id: string, s?: AbortSignal) => request<Preview>(`${ANN}/previews/${encodeURIComponent(id)}`, {}, s),
  stopPreview: (id: string) => post<Preview>(`${ANN}/previews/${encodeURIComponent(id)}/stop`, {}),
  createRun: (previewId: string, key: string) => post<Task>(`${ANN}/runs`, { previewId }, key),
  task: (id: string, s?: AbortSignal) => request<Task>(`${ANN}/runs/${encodeURIComponent(id)}`, {}, s),
  history: (cursor?: string | null, s?: AbortSignal) => request<History>(url(`${ANN}/runs`, { cursor, limit: String(clientPolicy.historyLimit) }), {}, s),
  related: (id: string, cursor?: string | null, s?: AbortSignal) => request<History>(url(`${ANN}/runs/${encodeURIComponent(id)}/related`, { cursor, limit: String(clientPolicy.historyLimit) }), {}, s),
  files: (id: string, result: ResultFilter, cursor?: string | null, s?: AbortSignal) => request<Files>(url(`${ANN}/runs/${encodeURIComponent(id)}/files`, { result, cursor, limit: String(clientPolicy.resultLimit) }), {}, s),
  stop: (id: string) => post<Task>(`${ANN}/runs/${encodeURIComponent(id)}/stop`, {}),
  continue: (id: string, key: string) => post<Task>(`${ANN}/runs/${encodeURIComponent(id)}/continue`, {}, key),
  retry: (id: string, artifactKey: string | null, key: string) => post<Task>(`${ANN}/runs/${encodeURIComponent(id)}/retries`,
    artifactKey ? { scope: "singleFailed", artifactKey } : { scope: "allFailed" }, key),
  recheck: (id: string, kind: RecheckKind) => post<Task>(`${ANN}/runs/${encodeURIComponent(id)}/recheck`, { kind }),
};
export function errorMessage(error: unknown): string { return error instanceof Error ? error.message : "暂不可获取，请重试"; }
