import { afterEach, describe, expect, it, vi } from "vitest";
import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { fetchXxm, XXM_TIMEOUT_MS } from "./apiClient";

vi.mock("../../../shared/api/wealthApiClient", () => ({ wealthFetch: vi.fn() }));
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers(); });
const params = { tsCode: "000001.SH", period: "m60" as const, startDate: "2026-04-01", endDate: "2026-10-13", limit: 500 };
function pendingUntilAbort() {
  vi.mocked(wealthFetch).mockImplementation((_url, options) => new Promise((_resolve, reject) => {
    options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }));
}

describe("XXM HTTP client", () => {
  it("uses the approved minute contract and preserves the backend error message", async () => {
    vi.mocked(wealthFetch).mockResolvedValue(new Response(JSON.stringify({ message: "研究指标来源存在缺口" }), { status: 503 }));
    await expect(fetchXxm(params, new AbortController().signal)).rejects.toThrow("来源存在缺口");
    const url = new URL(String(vi.mocked(wealthFetch).mock.calls[0]![0]));
    expect(url.pathname).toBe("/api/v1/wealth/market/index-detail/minute-xxm-signals");
    expect([...url.searchParams.keys()].sort()).toEqual(["endDate", "freq", "limit", "startDate", "tsCode"]);
    expect(url.searchParams.get("freq")).toBe("60");
  });
  it("aborts at the 5 second limit and returns a local retry message", async () => {
    vi.useFakeTimers(); pendingUntilAbort();
    const promise = fetchXxm(params, new AbortController().signal);
    const failure = expect(promise).rejects.toThrow("加载超时");
    await vi.advanceTimersByTimeAsync(XXM_TIMEOUT_MS);
    await failure;
    expect(vi.mocked(wealthFetch).mock.calls[0]![1]?.signal?.aborted).toBe(true);
    expect(vi.getTimerCount()).toBe(0);
  });
  it("cancels a switched request without presenting it as a timeout", async () => {
    pendingUntilAbort();
    const controller = new AbortController();
    const promise = fetchXxm(params, controller.signal);
    const failure = expect(promise).rejects.toThrow("Aborted");
    controller.abort();
    await failure;
  });
  it("explains a network failure without exposing browser implementation text", async () => {
    vi.mocked(wealthFetch).mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(fetchXxm(params, new AbortController().signal)).rejects.toThrow("暂时无法连接");
  });
});
