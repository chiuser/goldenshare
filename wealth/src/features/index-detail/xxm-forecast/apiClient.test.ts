import {afterEach,expect,it,vi} from "vitest";
import {wealthFetch} from "../../../shared/api/wealthApiClient";
import {indexDetailRequests} from "../api/indexDetailRequestScheduler";
import {fetchForecast,sendForecast} from "./apiClient";
import {forecastDebugFixture,forecastFixture} from "./forecastFixtures.test-support";
import {fetchDebugForecast} from "../debug/apiClient";
import {adaptForecast} from "./adapter";
import {decodeForecastDebug} from "../debug/forecastDebugContract";
import type {ForecastPeriod} from "./types";
vi.mock("../../../shared/api/wealthApiClient",()=>({wealthFetch:vi.fn()}));
afterEach(()=>{vi.clearAllMocks();vi.restoreAllMocks();});
it.each([4999,5001])("does not renew the deadline after fetching or decoding at %dms",async end=>{
  let now=0;vi.spyOn(performance,"now").mockImplementation(()=>now);
  vi.mocked(wealthFetch).mockImplementation(async()=>{now=4990;return new Response(JSON.stringify(forecastDebugFixture("000001.SH")));});
  const pending=sendForecast("000001.SH","day",undefined,new AbortController().signal,5000,"debug/",(raw,context)=>{
    const {debug,...fields}=raw as ReturnType<typeof forecastDebugFixture>;
    const response=adaptForecast(fields,context);
    const details=decodeForecastDebug(debug,{...context,response});
    now=end;
    return {...response,debug:details};
  });
  if(end<5000)expect((await pending).deadline).toBe(5000);else await expect(pending).rejects.toThrow("超时");
  expect(String(vi.mocked(wealthFetch).mock.calls[0]![0])).toContain("/debug/xxm-key-point-forecast");
});
it("normal requests omit debug and retain source errors",async()=>{
  vi.mocked(wealthFetch).mockResolvedValueOnce(new Response(JSON.stringify(forecastFixture("000001.SH"))));
  expect((await fetchForecast("000001.SH","day",undefined,new AbortController().signal)).response.status).toBe("READY");
  expect(new URL(String(vi.mocked(wealthFetch).mock.calls[0]![0]),window.location.origin).searchParams.has("debug")).toBe(false);
  vi.mocked(wealthFetch).mockResolvedValueOnce(new Response(JSON.stringify({message:"来源不完整"}),{status:503}));
  await expect(fetchForecast("000001.SH","day",undefined,new AbortController().signal)).rejects.toThrow("来源不完整");
});

it.each(["day","m30","m60","m90","m120"] as const)("preserves an unbounded debug range through the actual %s client",async period=>{
  // LLD 21.13, real 2026-10-27 boundary; only HTTP is replaced.
  const raw=forecastDebugFixture("399001.SZ",period);
  raw.debug.conditions[0]!.priceRanges=[{lower:3779.307688860061,upper:null,lowerInclusive:true,upperInclusive:false,displayLower:3780,displayUpper:null}];
  vi.mocked(wealthFetch).mockResolvedValueOnce(new Response(JSON.stringify(raw)));
  const result=await fetchDebugForecast("399001.SZ",period,undefined,new AbortController().signal);
  expect(result.response).toHaveProperty("debug.conditions.0.priceRanges.0",{lower:3779.307688860061,upper:null,lowerInclusive:true,upperInclusive:false,displayLower:3780,displayUpper:null});
  expect(result.deadline).toBeGreaterThan(performance.now());
  expect(vi.mocked(wealthFetch)).toHaveBeenCalledTimes(1);
});

it.each([0,1] as const)("sends the requested non-Shanghai m30 identity and replay endpoint, debug=%s",async debug=>{
  const tsCode="399001.SZ",asOf="2023-01-10T15:00:00+08:00";
  const raw=debug?forecastDebugFixture(tsCode,"m30",asOf):forecastFixture(tsCode,"m30",asOf);
  vi.mocked(wealthFetch).mockResolvedValueOnce(new Response(JSON.stringify(raw)));
  const {response}=await (debug?fetchDebugForecast:fetchForecast)(tsCode,"m30",asOf,new AbortController().signal);
  const url=new URL(String(vi.mocked(wealthFetch).mock.calls[0]![0]),window.location.origin);
  expect(Object.fromEntries(url.searchParams)).toEqual({tsCode,period:"m30",asOf});
  expect(response).toEqual(raw);
  expect(response.targetEndpoint).toBe("2023-01-11T10:00:00+08:00");
});

it.each([
  {tsCode:"000001.SH"},
  {period:"m60"},
  {requestedAsOf:"2023-01-10T14:30:00+08:00"},
])("rejects another response identity instead of accepting a valid-looking m30 result: %j",async patch=>{
  const asOf="2023-01-10T15:00:00+08:00";
  vi.mocked(wealthFetch).mockResolvedValueOnce(new Response(JSON.stringify({...forecastFixture("399001.SZ","m30",asOf),...patch})));
  await expect(fetchForecast("399001.SZ","m30",asOf,new AbortController().signal)).rejects.toThrow("顶底识别数据与合同不一致");
});

it("runs five real forecast clients exclusively after at most two light jobs and starts their deadlines after queuing",async()=>{
  // Only transport and light work are replaced; all five clients use the actual page scheduler.
  let now=0,active=0;
  vi.spyOn(performance,"now").mockImplementation(()=>now);
  const started:string[]=[],lightRelease:Array<()=>void>=[],forecastRelease:Array<()=>void>=[];
  const light=(name:string)=>indexDetailRequests.run("chart",()=>{
    started.push(name);active++;
    return new Promise<void>(resolve=>lightRelease.push(()=>{active--;resolve();}));
  });
  const lightRequests=[light("bars"),light("indicators"),light("next-chart")];
  vi.mocked(wealthFetch).mockImplementation(input=>{
    const url=new URL(String(input),window.location.origin),period=url.searchParams.get("period") as ForecastPeriod;
    expect(active).toBe(0);
    active++;started.push(period);
    return new Promise<Response>(resolve=>forecastRelease.push(()=>{
      active--;resolve(new Response(JSON.stringify(forecastFixture("399001.SZ",period))));
    }));
  });
  const periods=["day","m30","m60","m90","m120"] as const;
  const forecasts=periods.map(period=>fetchForecast("399001.SZ",period,undefined,new AbortController().signal));
  await vi.waitFor(()=>expect(started).toEqual(["bars","indicators"]));
  expect(active).toBe(2);
  lightRelease[0]!();
  await vi.waitFor(()=>expect(started).toEqual(["bars","indicators","next-chart"]));
  expect(active).toBe(2);
  lightRelease[1]!();
  await vi.waitFor(()=>expect(active).toBe(1));
  expect(vi.mocked(wealthFetch)).not.toHaveBeenCalled();
  // Queue time exceeds the existing 5s client limit; it must not consume execution time.
  now=6000;lightRelease[2]!();
  for(const [index,period] of periods.entries()){
    await vi.waitFor(()=>expect(started).toEqual(["bars","indicators","next-chart",...periods.slice(0,index+1)]));
    expect(active).toBe(1);
    expect(vi.mocked(wealthFetch)).toHaveBeenCalledTimes(index+1);
    forecastRelease[index]!();
    const result=await forecasts[index]!;
    expect(result.response.period).toBe(period);
    expect(result.deadline).toBe(11000);
  }
  await Promise.all(lightRequests);
  expect(active).toBe(0);
});
