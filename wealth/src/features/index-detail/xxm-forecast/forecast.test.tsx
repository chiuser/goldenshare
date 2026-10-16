import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { XxmForecastCard } from "./XxmForecastCard";
import { adaptForecast } from "./adapter";
import { useXxmForecast } from "./useXxmForecast";
import { fetchForecast } from "./apiClient";
import { FORECAST_PERIODS, type ForecastPeriod, type ForecastResponse, type ForecastRows } from "./types";
vi.mock("./apiClient", () => ({ fetchForecast: vi.fn() }));
const mocked = vi.mocked(fetchForecast);
function response(period: ForecastPeriod, asOf?: string): ForecastResponse {
  return { tsCode:"000001.SH",period,forecastVersion:"xxm-key-point-forecast-v0.2-a1",forecastSpecHash:"a".repeat(64),detectorSpecHash:"b".repeat(64),
    sourceInputId:"c".repeat(64),calendarInputId:"d".repeat(64),computedThrough:asOf??(period==="day"?"2026-10-13":"2026-10-13T15:00:00+08:00"),requestedAsOf:asOf??null,
    mode:asOf?"REPLAY":"LATEST",dataStatus:"READY",rearmContext: null, ordinaryState:"NONE",direction:"BOTTOM",status:"NO_CANDIDATE",reasonCode:"NO_ENTRY_RANGE",precisionPolicy:period==="day"?"rounded3_guarded":"full_float",
    forecastId:"f".repeat(64),targetEndpoint:null,barsAhead:null,activation:null,assumption:null,targetEntryRanges:[],targetEntryExclusions:[],relations:[],commonConditions:[],examples:[],applicabilityText:"",invalidationText:"",confirmedAt:null,confirmedDirection:null,refreshAfterMs:60000,
    display:{statusLabel:"暂无候选",targetText:"暂无有效候选时点",conditionsText:"当前参考情景内暂无时点。",asOfText:"截至10/13"}};
}
beforeEach(() => mocked.mockReset());
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });

it("rejects another period, stale asOf and invalid successful fields", () => {
  expect(() => adaptForecast(response("m90"),"day")).toThrow();
  expect(() => adaptForecast(response("day","2026-10-12"),"day","2026-10-13")).toThrow();
  expect(() => adaptForecast({...response("day"),status:"READY"},"day")).toThrow();
  expect(adaptForecast(response("day"),"day").status).toBe("NO_CANDIDATE");
});

it("displays four periods, complete text, independent failure and retry without scores", () => {
  const rows = Object.fromEntries(FORECAST_PERIODS.map(p=>[p,{phase:"ready",response:response(p),error:""}])) as ForecastRows;
  rows.m60={phase:"error",response:null,error:"网络异常"};
  rows.day.response!.display.conditionsText="钝化触发：10/15收盘不高于3764.1546点。\n未触发：10/15收在3764.1548～3950.9680点。\n推算失效：不低于3950.9681点。";
  const retry=vi.fn();
  const {container}=render(<XxmForecastCard rows={rows} retry={retry}/>);
  expect(container.querySelectorAll("article")).toHaveLength(4);
  expect(screen.getByText(/3764.1546/)).toBeVisible();
  fireEvent.click(screen.getByRole("button",{name:"重试60 分钟关键点预判"}));
  expect(retry).toHaveBeenCalledWith("m60");
  expect(screen.queryByText(/评分|可信度|买入|卖出/)).not.toBeInTheDocument();
});

it("loads only after activation, delegates concurrency to clients and retries one row", async () => {
  const pending: Array<{p:ForecastPeriod;resolve:(v:ForecastResponse)=>void;reject:(e:Error)=>void}> = [];
  mocked.mockImplementation(p=>new Promise((resolve,reject)=>pending.push({p,resolve,reject})));
  const {result,rerender}=renderHook((props)=>useXxmForecast(props),{initialProps:{active:false,tsCode:"000001.SH",minutes:true}});
  expect(mocked).not.toHaveBeenCalled();
  rerender({active:true,tsCode:"000001.SH",minutes:true});
  await waitFor(()=>expect(pending).toHaveLength(4));
  await act(async()=>pending[0].resolve(response(pending[0].p)));
  await act(async()=>pending[1].reject(new Error("failed")));
  await act(async()=>{pending[2].resolve(response(pending[2].p));pending[3].resolve(response(pending[3].p));});
  expect(result.current.rows.day.phase).toBe("ready");
  expect(result.current.rows.m60.phase).toBe("error");
  expect(result.current.rows.m90.phase).toBe("ready");
  rerender({active:true,tsCode:"000001.SH",minutes:true});
  expect(mocked).toHaveBeenCalledTimes(4);
  act(()=>result.current.retry("m60"));
  expect(mocked).toHaveBeenCalledTimes(5);
  expect(pending[4].p).toBe("m60");
});

it("polls latest responses using API timing and replaces only real returned state", async () => {
  vi.useFakeTimers();
  mocked.mockImplementation(async p=>response(p));
  const {result,unmount}=renderHook(()=>useXxmForecast({active:true,tsCode:"000001.SH",minutes:true}));
  await act(async()=>{await Promise.resolve();await Promise.resolve();});
  expect(mocked).toHaveBeenCalledTimes(4);
  expect(result.current.rows.day.phase).toBe("ready");
  mocked.mockImplementation(async p=>({...response(p),computedThrough:p==="day"?"2026-10-14":"2026-10-14T15:00:00+08:00",forecastId:"e".repeat(64)}));
  await act(async()=>{vi.advanceTimersByTime(60000);await Promise.resolve();await Promise.resolve();});
  expect(mocked).toHaveBeenCalledTimes(8);
  expect(result.current.rows.day.response?.computedThrough).toBe("2026-10-14");
  unmount();
});

it("pins historical asOf, never polls, and closed minutes do not dispatch", async () => {
  vi.useFakeTimers();
  mocked.mockImplementation(async (p,a)=>response(p,a));
  renderHook(()=>useXxmForecast({active:true,tsCode:"000001.SH",historicalDate:"2026-10-13",minutes:false}));
  await act(async()=>{await Promise.resolve();});
  expect(mocked).toHaveBeenCalledTimes(1);
  expect(mocked.mock.calls[0].slice(0,2)).toEqual(["day","2026-10-13"]);
  await act(async()=>vi.advanceTimersByTime(120000));
  expect(mocked).toHaveBeenCalledTimes(1);
});

it("cancels hidden/outgoing requests and ignores old responses on object change", async () => {
  let hidden=false;
  vi.spyOn(document,"visibilityState","get").mockImplementation(()=>hidden?"hidden":"visible");
  const pending:Array<{p:ForecastPeriod;signal:AbortSignal;resolve:(v:ForecastResponse)=>void}>=[];
  mocked.mockImplementation((p,a,signal)=>new Promise(resolve=>pending.push({p,signal,resolve})));
  const {result,rerender}=renderHook((props)=>useXxmForecast(props),{initialProps:{active:true,tsCode:"000001.SH",minutes:true}});
  expect(pending).toHaveLength(4);
  hidden=true;
  act(()=>document.dispatchEvent(new Event("visibilitychange")));
  expect(pending.every(p=>p.signal.aborted)).toBe(true);
  hidden=false;
  act(()=>document.dispatchEvent(new Event("visibilitychange")));
  expect(pending).toHaveLength(8);
  rerender({active:true,tsCode:"399001.SZ",minutes:true});
  await act(async()=>{for(const p of pending)p.resolve(response(p.p));});
  expect(result.current.rows.day.response).toBeNull();
  expect(mocked).toHaveBeenCalledTimes(8);
});


it("rejects legacy fields and accepts activation-only state without inventing a structure date",()=>{
  const v=response("day");
  expect(()=>adaptForecast({...v,scenarios:[]} as unknown as ForecastResponse,"day")).toThrow();
  const entry={...v,status:"ENTRY_ONLY",reasonCode:"NO_CONFIRMATION_IN_HORIZON",activation:{endpoint:"2026-10-14",ranges:[{entryRangeId:"entry-1",priceRange:{lower:3400,upper:3764,lowerInclusive:false,upperInclusive:false},reference:{startTime:"2026-01-01",endTime:"2026-01-02",price:3600,dif:-10}}],exclusions:[]}} as ForecastResponse;
  expect(adaptForecast(entry,"day").targetEndpoint).toBeNull();
  expect(()=>adaptForecast({...entry,activation:{...entry.activation!,ranges:[{...entry.activation!.ranges[0],priceRange:{lower:3700,upper:3600,lowerInclusive:false,upperInclusive:false}}]}},"day")).toThrow();
});


it("rejects archived v0.2 responses instead of mixing them with a1",()=>{
  for(const period of FORECAST_PERIODS){
    for(const mode of ["latest","cold"]){
      const file=resolve(process.cwd(),"../reports/xxm_forecast_range_implementation_20261014",`http_${mode}_${period}.json`);
      const value=JSON.parse(readFileSync(file,"utf8")) as ForecastResponse;
      expect(()=>adaptForecast(value,period,value.requestedAsOf??undefined)).toThrow();
    }
  }
});

it("renders current real producer copy for four periods without dropping protected conditions or reconstructing prices",()=>{
  {
    const indexes={day:5,m60:6,m90:7,m120:8};
    const rows=Object.fromEntries(FORECAST_PERIODS.map(period=>{
      const file=resolve(process.cwd(),"../reports/xxm_same_segment_a1_implementation_20261016/api",`api_forecast_${indexes[period]}_${period}.json`);
      const value=JSON.parse(readFileSync(file,"utf8")) as ForecastResponse;
      const adapted=adaptForecast(value,period,value.requestedAsOf??undefined);
      expect(adapted).toBe(value);
      expect(adapted.display.conditionsText).not.toMatch(/前置收盘|目标收盘|充分条件|差异举例|临界点/);
      return [period,{phase:"ready",response:adapted,error:""}];
    })) as ForecastRows;
    const view=render(<XxmForecastCard rows={rows} retry={vi.fn()}/>);
    for(const period of FORECAST_PERIODS){
      const row=view.container.querySelector(`[data-period="${period}"]`)!;
      expect(row.querySelector("p")?.textContent).toBe(rows[period].response!.display.conditionsText);
      expect(row.querySelector(".xxm-forecast-target")?.textContent).toBe(rows[period].response!.display.targetText);
    }
    const day=view.container.querySelector('[data-period="day"]')!;
    expect(day).toHaveTextContent("钝化触发");
    expect(day).toHaveTextContent("未触发");
    expect(day).toHaveTextContent("推算失效");
    expect(day).toHaveTextContent("结构成立");
    expect(day).not.toHaveTextContent("3457");
    expect(day).not.toHaveTextContent("4112");
    expect(rows.m90.response!.status).toBe("CONDITIONAL_ENTRY");
    expect(rows.m90.response!.display.statusLabel).toBe("近期暂无条件");
    expect(rows.m90.response!.activation!.ranges.length).toBeGreaterThan(0);
    expect(view.container.querySelector("footer")?.textContent).toBe("新收盘后更新本周期点位和时点。");
    expect(view.container).not.toHaveTextContent(/评分|可信度|前置收盘/);
    view.unmount();
  }
});
