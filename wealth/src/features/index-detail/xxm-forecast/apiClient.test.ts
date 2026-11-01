import {afterEach,expect,it,vi} from "vitest";
import {wealthFetch} from "../../../shared/api/wealthApiClient";
import {fetchForecast} from "./apiClient";
import {forecastDebugFixture,forecastFixture} from "./forecastFixtures.test-support";
import {decodeForecastDebug} from "../debug/forecastDebugContract";
vi.mock("../../../shared/api/wealthApiClient",()=>({wealthFetch:vi.fn()}));
afterEach(()=>{vi.clearAllMocks();vi.restoreAllMocks();});
it.each([4999,5001])("does not renew the deadline after fetching or decoding at %dms",async end=>{
  let now=0;vi.spyOn(performance,"now").mockImplementation(()=>now);
  vi.mocked(wealthFetch).mockImplementation(async()=>{now=4990;return new Response(JSON.stringify(forecastDebugFixture()));});
  const pending=fetchForecast("day",undefined,new AbortController().signal,{debug:1,decodeDebug:(raw,context)=>{const result=decodeForecastDebug(raw,context);now=end;return result;}});
  if(end<5000)expect((await pending).deadline).toBe(5000);else await expect(pending).rejects.toThrow("超时");
  expect(String(vi.mocked(wealthFetch).mock.calls[0]![0])).toContain("debug=1");
});
it("normal requests omit debug and retain source errors",async()=>{
  vi.mocked(wealthFetch).mockResolvedValueOnce(new Response(JSON.stringify(forecastFixture())));
  expect((await fetchForecast("day",undefined,new AbortController().signal)).response.status).toBe("READY");
  expect(new URL(String(vi.mocked(wealthFetch).mock.calls[0]![0]),window.location.origin).searchParams.has("debug")).toBe(false);
  vi.mocked(wealthFetch).mockResolvedValueOnce(new Response(JSON.stringify({message:"来源不完整"}),{status:503}));
  await expect(fetchForecast("day",undefined,new AbortController().signal)).rejects.toThrow("来源不完整");
});

it.each(["day","m60","m90","m120"] as const)("preserves an unbounded debug range through the actual %s client",async period=>{
  // LLD 21.13, real 2026-10-27 boundary; only HTTP is replaced.
  const raw=forecastDebugFixture(period);
  raw.debug.conditions[0]!.priceRanges=[{lower:3779.307688860061,upper:null,lowerInclusive:true,upperInclusive:false,displayLower:3780,displayUpper:null}];
  vi.mocked(wealthFetch).mockResolvedValueOnce(new Response(JSON.stringify(raw)));
  const result=await fetchForecast(period,undefined,new AbortController().signal,{debug:1,decodeDebug:decodeForecastDebug});
  expect(result.response).toHaveProperty("debug.conditions.0.priceRanges.0",{lower:3779.307688860061,upper:null,lowerInclusive:true,upperInclusive:false,displayLower:3780,displayUpper:null});
  expect(result.deadline).toBeGreaterThan(performance.now());
  expect(vi.mocked(wealthFetch)).toHaveBeenCalledTimes(1);
});
