import { afterEach, describe, expect, it, vi } from "vitest";
import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { fetchXxm, sendXxm, XXM_TIMEOUT_MS } from "./apiClient";

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
  it.each(["day", "m30", "m60", "m90", "m120"] as const)("requests and decodes the actual non-Shanghai index for %s", async period => {
    const { goldXxmFixture: xxmFixture } = await import("./xxmFixtures.test-support");
    const fixture = xxmFixture("399001.SZ", period);
    vi.mocked(wealthFetch).mockResolvedValue(new Response(JSON.stringify(fixture.response)));
    const { response } = await fetchXxm({ ...params, tsCode: "399001.SZ", period }, new AbortController().signal);
    const url = new URL(String(vi.mocked(wealthFetch).mock.calls[0]![0]));
    expect(url.searchParams.get("tsCode")).toBe("399001.SZ");
    expect(url.pathname).toBe(`/api/v1/wealth/market/index-detail/${period === "day" ? "xxm-signals" : "minute-xxm-signals"}`);
    expect(url.searchParams.get(period === "day" ? "period" : "freq")).toBe(period === "day" ? "day" : period.slice(1));
    expect(response).toEqual(fixture.response);
    expect(response.events).toHaveLength(2);
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
    const failure = expect(promise).rejects.toMatchObject({ name: "AbortError" });
    controller.abort();
    await failure;
  });
  it("explains a network failure without exposing browser implementation text", async () => {
    vi.mocked(wealthFetch).mockRejectedValue(new TypeError("Failed to fetch"));
    await expect(fetchXxm(params, new AbortController().signal)).rejects.toThrow("暂时无法连接");
  });
});

it.each([4999,5001])("keeps the original deadline through real debug decoding at %dms", async end => {
  const { xxmDebugFixture } = await import("./xxmFixtures.test-support");
  const { decodeDebugXxmResponse } = await import("../debug/xxmAdapter");
  let now=0;vi.spyOn(performance,"now").mockImplementation(()=>now);
  vi.mocked(wealthFetch).mockImplementation(async()=>{now=4990;return new Response(JSON.stringify(xxmDebugFixture("000001.SH").response));});
  const pending = sendXxm({...params,period:"day"}, new AbortController().signal, 5000, "debug/", (raw, context) => {
    const data = decodeDebugXxmResponse(raw, context); now = end; return data;
  });
  try {
    if(end<5000)expect((await pending).deadline).toBe(5000);
    else await expect(pending).rejects.toThrow("超时");
    expect(new URL(String(vi.mocked(wealthFetch).mock.calls[0]![0])).pathname).toContain("/debug/xxm-signals");
  } finally {vi.restoreAllMocks();}
});
