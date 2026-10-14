import { afterEach, expect, it, vi } from "vitest";
import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { fetchForecast } from "./apiClient";
vi.mock("../../../shared/api/wealthApiClient",()=>({wealthFetch:vi.fn()}));
afterEach(()=>{vi.useRealTimers();vi.resetAllMocks();});
it("encodes historical minute endpoints and exposes actual HTTP errors",async()=>{
  vi.mocked(wealthFetch).mockResolvedValue(new Response(JSON.stringify({message:"当前环境未开放"}),{status:404}));
  await expect(fetchForecast("m90","2026-10-13T15:00:00+08:00",new AbortController().signal)).rejects.toThrow("当前环境未开放");
  const url=String(vi.mocked(wealthFetch).mock.calls[0][0]);
  expect(url).toContain("period=m90");expect(url).toContain("%2B08%3A00");
});
it("uses existing five second timeout and aborts the outgoing request",async()=>{
  vi.useFakeTimers();
  vi.mocked(wealthFetch).mockImplementation((url,options)=>new Promise((resolve,reject)=>options?.signal?.addEventListener("abort",()=>reject(new DOMException("aborted","AbortError")))));
  const request=fetchForecast("day",undefined,new AbortController().signal);
  const assertion=expect(request).rejects.toThrow("加载超时");
  await vi.advanceTimersByTimeAsync(5000);await assertion;
});
