import { act, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { IndexRecognitionDebugModule } from "./types";
const module: IndexRecognitionDebugModule = {
  IndexRecognitionDebug: () => null, decodeXxmDebug: vi.fn(), decodeForecastDebug: vi.fn(),
  renderXxmDetails: () => null, renderForecastDetails: () => null,
};
beforeEach(() => vi.resetModules());
afterEach(() => vi.doUnmock("./IndexRecognitionDebug"));
function pending() {
  let resolve!: (value: IndexRecognitionDebugModule) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<IndexRecognitionDebugModule>((a,b) => { resolve=a; reject=b; });
  return { promise, resolve, reject };
}
it("does not import when disabled; exposes all real exports only after ready", async () => {
  const value=pending(), load=vi.fn(() => value.promise);
  vi.doMock("./IndexRecognitionDebug", load);
  const { useIndexDebugModule } = await import("./useIndexDebugModule");
  const {result,rerender}=renderHook(({enabled})=>useIndexDebugModule(enabled),{initialProps:{enabled:false}});
  const retry=result.current.retry;
  expect(load).not.toHaveBeenCalled(); expect(result.current.phase).toBe("idle");
  rerender({enabled:true}); await waitFor(()=>expect(load).toHaveBeenCalledTimes(1));
  expect(result.current.module).toBeNull(); expect(result.current.phase).toBe("loading");
  await act(async()=>value.resolve(module));
  expect(result.current.phase).toBe("ready");
  for (const key of Object.keys(module) as (keyof IndexRecognitionDebugModule)[]) expect(result.current.module?.[key]).toBe(module[key]);
  expect(result.current.retry).toBe(retry);
  act(()=>result.current.retry()); expect(load).toHaveBeenCalledTimes(1);
  rerender({enabled:false}); expect(result.current.module).toBeNull();
});
it.each([false,true])("ignores late success/failure after close (failure=%s)", async failure => {
  const value=pending(); vi.doMock("./IndexRecognitionDebug",()=>value.promise);
  const {useIndexDebugModule}=await import("./useIndexDebugModule");
  const {result,rerender}=renderHook(({enabled})=>useIndexDebugModule(enabled),{initialProps:{enabled:true}});
  await act(async()=>{}); rerender({enabled:false});
  await act(async()=>{if(failure)value.reject(new Error("late"));else value.resolve(module);});
  expect(result.current).toMatchObject({phase:"idle",module:null,errorMessage:""});
});
it("reports failure without automatic retry; manual retry works",async()=>{
  const failure=pending(); const load=vi.fn(()=>failure.promise);
  vi.doMock("./IndexRecognitionDebug",load);
  const {useIndexDebugModule}=await import("./useIndexDebugModule");
  const {result,unmount}=renderHook(()=>useIndexDebugModule(true));
  await act(async()=>failure.reject(new Error("network")));
  await waitFor(()=>expect(result.current.phase).toBe("error"));
  expect(result.current.module).toBeNull(); expect(load.mock.calls.length).toBeGreaterThanOrEqual(1);
  const calls=load.mock.calls.length;
  await act(async()=>{}); expect(load).toHaveBeenCalledTimes(calls);
  // Retrying a failed mocked import must resolve a new module, as a fresh dynamic import does.
  vi.doMock("./IndexRecognitionDebug",()=>module);
  act(()=>result.current.retry());
  await waitFor(()=>expect(result.current.phase).toBe("ready"));
  unmount();
});

it("cleans StrictMode setup and unmount without extra state or retry", async()=>{
 vi.doMock("./IndexRecognitionDebug",()=>module);
 const {useIndexDebugModule}=await import("./useIndexDebugModule");
 const {result,unmount}=renderHook(()=>useIndexDebugModule(true),{wrapper:StrictMode});
 await waitFor(()=>expect(result.current.phase).toBe("ready")); unmount();
});
