import {act,fireEvent,render,renderHook,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,expect,it,vi} from "vitest";
import {useXxmForecast} from "./useXxmForecast";
import {fetchForecast} from "./apiClient";
import {XxmForecastCard} from "./XxmForecastCard";
import {forecastFixture,forecastDebugFixture} from "./forecastFixtures.test-support";
import {renderForecastDetails} from "../debug/IndexRecognitionDebug";
import {decodeForecastDebug} from "../debug/forecastDebugContract";
import type {ForecastPeriod,ForecastRequestResult,ForecastRows} from "./types";
vi.mock("./apiClient",()=>({fetchForecast:vi.fn()}));
const mocked=vi.mocked(fetchForecast);
const initial={active:false,tsCode:"000001.SH",minutes:true,enabled:true,debug:0 as const};
const wrapped=(p:ForecastPeriod)=>({response:forecastFixture(p),deadline:performance.now()+5000});
beforeEach(()=>mocked.mockReset());afterEach(()=>{vi.useRealTimers();vi.unstubAllEnvs();vi.restoreAllMocks();});
it("loads only after activation, supports independent failures and retries one period",async()=>{const pending:Array<{p:ForecastPeriod;resolve:(v:ForecastRequestResult)=>void;reject:(e:Error)=>void}>=[];mocked.mockImplementation(p=>new Promise((resolve,reject)=>pending.push({p,resolve,reject})));const {result,rerender}=renderHook(props=>useXxmForecast(props),{initialProps:initial});expect(mocked).not.toHaveBeenCalled();rerender({...initial,active:true});await waitFor(()=>expect(pending).toHaveLength(4));await act(async()=>{pending[0]!.resolve(wrapped("day"));pending[1]!.reject(new Error("source failed"));pending[2]!.resolve(wrapped("m90"));pending[3]!.resolve(wrapped("m120"));});expect(result.current.rows.day.phase).toBe("ready");expect(result.current.rows.m60.phase).toBe("error");expect(result.current.rows.m90.phase).toBe("ready");act(()=>result.current.retry("m60"));expect(pending.at(-1)!.p).toBe("m60");expect(pending).toHaveLength(5);});
it.each([{dev:false,enabled:true},{dev:true,enabled:false}])("does not request when DEV=$dev and enabled=$enabled",({dev,enabled})=>{
  vi.stubEnv("DEV",dev);
  const {result}=renderHook(()=>useXxmForecast({...initial,active:true,enabled}));
  act(()=>result.current.retry("day"));
  expect(mocked).not.toHaveBeenCalled();
});
it("aborts and ignores late values on deactivation",async()=>{let resolve!:(v:ForecastRequestResult)=>void;mocked.mockImplementation(()=>new Promise(r=>{resolve=r;}));const {result,rerender}=renderHook(props=>useXxmForecast(props),{initialProps:{...initial,active:true,minutes:false}});await waitFor(()=>expect(mocked).toHaveBeenCalledTimes(1));const signal=mocked.mock.calls[0]![2];rerender({...initial,active:false,minutes:false});expect(signal.aborted).toBe(true);await act(async()=>resolve(wrapped("day")));expect(result.current.rows.day.response).toBeNull();});
it("uses the original deadline for the final commit and clears failed old responses",async()=>{mocked.mockResolvedValue({response:forecastFixture(),deadline:performance.now()-1});const {result}=renderHook(()=>useXxmForecast({...initial,active:true,minutes:false}));await waitFor(()=>expect(result.current.rows.day.phase).toBe("error"));expect(result.current.rows.day.response).toBeNull();});
it("does not poll historical dates and keeps the date on manual retry",async()=>{
  vi.useFakeTimers();
  const asOf="2023-01-10";
  mocked.mockImplementation(async()=>({response:forecastFixture("day",asOf),deadline:performance.now()+5000}));
  const {result,unmount}=renderHook(()=>useXxmForecast({...initial,active:true,minutes:false,historicalDate:asOf}));
  await act(async()=>{await Promise.resolve();});
  expect(result.current.rows.day.phase).toBe("ready");
  await act(async()=>{await vi.advanceTimersByTimeAsync(60000);});
  expect(mocked).toHaveBeenCalledTimes(1);
  await act(async()=>{result.current.retry("day");await Promise.resolve();});
  expect(mocked.mock.calls.map(c=>c[1])).toEqual([asOf,asOf]);
  unmount();expect(vi.getTimerCount()).toBe(0);
});
it("polls latest by the backend interval and stops on deactivation",async()=>{vi.useFakeTimers();mocked.mockImplementation(async p=>wrapped(p));const {rerender,unmount}=renderHook(props=>useXxmForecast(props),{initialProps:{...initial,active:true,minutes:false}});await act(async()=>{await Promise.resolve();});expect(mocked).toHaveBeenCalledTimes(1);await act(async()=>{await vi.advanceTimersByTimeAsync(60000);});expect(mocked).toHaveBeenCalledTimes(2);rerender({...initial,active:false,minutes:false});await act(async()=>{await vi.advanceTimersByTimeAsync(60000);});expect(mocked).toHaveBeenCalledTimes(2);unmount();expect(vi.getTimerCount()).toBe(0);});
it("renders backend text and necessary notices; auxiliary renderer is optional and real",()=>{const rows=Object.fromEntries((["day","m60","m90","m120"] as const).map(p=>[p,{phase:"ready",response:forecastFixture(p),error:""}])) as ForecastRows;rows.day.response=forecastDebugFixture();rows.m60={phase:"error",response:null,error:"网络异常"};const retry=vi.fn();const {rerender}=render(<XxmForecastCard rows={rows} retry={retry}/>);expect(screen.getAllByText("只适用下一根完成收盘。",{selector:"small"})[0]).toBeVisible();expect(screen.queryByText("计算依据")).not.toBeInTheDocument();fireEvent.click(screen.getByRole("button",{name:"重试60 分钟关键点预判"}));expect(retry).toHaveBeenCalledWith("m60");rerender(<XxmForecastCard rows={rows} retry={retry} renderDebugDetails={renderForecastDetails}/>);expect(screen.getByText("计算依据")).toBeVisible();expect(screen.queryByText(/评分|可信度|买入|卖出/)).not.toBeInTheDocument();});

// F14: the actual owner/mode effects run; only the HTTP client is replaced.
it("cancels the old request when changing index and ignores its late result",async()=>{
  let resolve!:(v:ForecastRequestResult)=>void;
  mocked.mockImplementation(()=>new Promise(r=>{resolve=r;}));
  const props={...initial,active:true,minutes:false};
  const {result,rerender}=renderHook(p=>useXxmForecast(p),{initialProps:props});
  await waitFor(()=>expect(mocked).toHaveBeenCalledTimes(1));
  const signal=mocked.mock.calls[0]![2];
  rerender({...props,tsCode:"399001.SZ"});
  expect(signal.aborted).toBe(true);
  await act(async()=>resolve(wrapped("day")));
  expect(mocked).toHaveBeenCalledTimes(1); // Other indexes are currently unsupported.
  expect(result.current.rows.day.response).toBeNull();
});

it("cancels the old ordinary request when switching to debug and accepts only the new result",async()=>{
  const pending:Array<(v:ForecastRequestResult)=>void>=[];
  mocked.mockImplementation(()=>new Promise(resolve=>pending.push(resolve)));
  const props:Parameters<typeof useXxmForecast>[0]={...initial,active:true,minutes:false,decodeDebug:decodeForecastDebug};
  const {result,rerender}=renderHook(p=>useXxmForecast(p),{initialProps:props});
  await waitFor(()=>expect(mocked).toHaveBeenCalledTimes(1));
  const oldSignal=mocked.mock.calls[0]![2];
  rerender({...props,debug:1});
  await waitFor(()=>expect(mocked).toHaveBeenCalledTimes(2));
  expect(oldSignal.aborted).toBe(true);
  expect(mocked.mock.calls[1]![3]?.debug).toBe(1);
  await act(async()=>pending[0]!(wrapped("day")));
  expect(result.current.rows.day.response).toBeNull();
  const response=forecastDebugFixture();
  await act(async()=>pending[1]!({response,deadline:performance.now()+5000}));
  expect(result.current.rows.day.response).toEqual(response);
});
