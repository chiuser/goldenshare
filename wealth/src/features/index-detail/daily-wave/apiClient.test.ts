import { afterEach, describe, expect, it, vi } from "vitest";
import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { fetchDailyWaveReview } from "./apiClient";
import { dailyWaveEmptyFixture } from "./dailyWaveFixtures.test-support";

vi.mock("../../../shared/api/wealthApiClient", () => ({ wealthFetch: vi.fn() }));
describe("daily-wave API client", () => {
  afterEach(() => vi.resetAllMocks());
  it("uses one tsCode, same caller signal and no-store without hidden retries", async () => {
    const payload = dailyWaveEmptyFixture(), controller = new AbortController();
    vi.mocked(wealthFetch).mockResolvedValue(new Response(JSON.stringify(payload)));
    expect(await fetchDailyWaveReview({ tsCode: "000001.SH" }, { signal: controller.signal })).toEqual(payload);
    expect(wealthFetch).toHaveBeenCalledTimes(1);
    const [input, options] = vi.mocked(wealthFetch).mock.calls[0]!;
    const url = new URL(String(input));
    expect(url.pathname).toBe("/api/v1/wealth/market/index-detail/daily-waves");
    expect([...url.searchParams]).toEqual([["tsCode", "000001.SH"]]);
    expect(options).toEqual({ method: "GET", cache: "no-store", signal: controller.signal });
  });
  it.each([401, 403, 422, 503, 500])("keeps HTTP %s as an error", async status => {
    vi.mocked(wealthFetch).mockResolvedValue(new Response(JSON.stringify({ code: "DAILY_WAVE_SOURCE_INVALID", message: "行情暂不可用" }), { status }));
    await expect(fetchDailyWaveReview({ tsCode: "000001.SH" }, { signal: new AbortController().signal }))
      .rejects.toMatchObject({ status, code: "DAILY_WAVE_SOURCE_INVALID", message: "行情暂不可用" });
    expect(wealthFetch).toHaveBeenCalledTimes(1);
  });
  it("does not return empty on a non-JSON failure", async () => {
    vi.mocked(wealthFetch).mockResolvedValue(new Response("bad response", { status: 503 }));
    await expect(fetchDailyWaveReview({ tsCode: "000001.SH" }, { signal: new AbortController().signal })).rejects.toThrow("计算失败");
  });
  it("retains caller cancellation rather than manufacturing a business result", async () => {
    const error = new DOMException("cancel", "AbortError");
    vi.mocked(wealthFetch).mockRejectedValue(error);
    await expect(fetchDailyWaveReview({ tsCode: "000001.SH" }, { signal: new AbortController().signal })).rejects.toBe(error);
  });
  it("retains cancellation while reading an HTTP error body", async () => {
    const controller = new AbortController(), error = new DOMException("cancel body", "AbortError");
    const response = new Response("", { status: 503 });
    vi.spyOn(response, "json").mockImplementation(async () => { controller.abort(); throw error; });
    vi.mocked(wealthFetch).mockResolvedValue(response);
    await expect(fetchDailyWaveReview({ tsCode: "000001.SH" }, { signal: controller.signal })).rejects.toBe(error);
  });
});
