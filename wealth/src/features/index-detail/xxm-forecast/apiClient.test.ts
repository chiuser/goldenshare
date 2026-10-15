import { afterEach, expect, it, vi } from "vitest";
import { wealthFetch } from "../../../shared/api/wealthApiClient";
import { fetchForecast } from "./apiClient";
import { indexDetailRequests } from "../api/indexDetailRequestScheduler";
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
it("starts the five second network timeout after the page queue dispatches",async()=>{
  vi.useFakeTimers();
  let release!:()=>void;
  const first=indexDetailRequests.run("xxm",()=>new Promise<void>(resolve=>{release=resolve;}));
  for(let i=0;i<8;i++)await Promise.resolve();
  vi.mocked(wealthFetch).mockImplementation((_url,options)=>new Promise((_resolve,reject)=>options?.signal?.addEventListener("abort",()=>reject(new DOMException("aborted","AbortError")))));
  const queued=fetchForecast("day",undefined,new AbortController().signal);
  const failure=expect(queued).rejects.toThrow("加载超时");
  await vi.advanceTimersByTimeAsync(6000);
  expect(wealthFetch).not.toHaveBeenCalled();
  release();await first;
  await vi.advanceTimersByTimeAsync(0);
  expect(wealthFetch).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(4999);
  expect(vi.mocked(wealthFetch).mock.calls[0][1]?.signal?.aborted).toBe(false);
  await vi.advanceTimersByTimeAsync(1);await failure;
});
