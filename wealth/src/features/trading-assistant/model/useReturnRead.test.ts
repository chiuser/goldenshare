import { act, renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Coverage, ReadContext } from "../api/generatedContracts";
import { TradingAssistantApiError } from "../api/tradingAssistantApi";
import { ReturnReadActiveContext, useReturnRead } from "./useReturnRead";

const mock = vi.hoisted(() => ({ status:vi.fn(), epoch:1 }));
vi.mock("../api/positionsApi", () => ({ getCalculationStatus:mock.status }));
vi.mock("../../auth/model/authStorage", () => ({ getAuthEpoch:()=>mock.epoch }));
const value = (id:string, pending=false) => ({ id, readContext:{ contextToken:id,accounts:[{ accountId:"one",calculationTargetVersion:"1" }] } as ReadContext,
  coverage:{ accounts:pending ? [{ accountId:"one",dataStatus:"Delayed" }] : [] } as unknown as Coverage });

describe("returns read lifecycle", () => {
  it("pauses hidden parent views without losing their selection or polling in the background", async () => {
    let active=true;
    const load=vi.fn().mockResolvedValue(value("same"));
    const hook=renderHook(()=>useReturnRead("selection",load),{ wrapper:({ children }:{ children:ReactNode })=>createElement(ReturnReadActiveContext.Provider,{ value:active },children) });
    await waitFor(()=>expect(hook.result.current.data).not.toBeNull());
    active=false; hook.rerender();
    expect(load.mock.calls[0][0].aborted).toBe(true);
    expect(hook.result.current.data?.readContext.contextToken).toBe("same");
    act(()=>document.dispatchEvent(new Event("visibilitychange")));
    expect(load).toHaveBeenCalledTimes(1);
    active=true; hook.rerender();
    await waitFor(()=>expect(load).toHaveBeenCalledTimes(2));
    hook.unmount();
  });
  beforeEach(() => { vi.clearAllMocks(); mock.epoch=1; vi.spyOn(document,"visibilityState","get").mockReturnValue("visible"); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
  it("aborts an old selection and rejects its late result", async () => {
    let finish!:(v:ReturnType<typeof value>)=>void;
    const load=vi.fn().mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve;})).mockResolvedValue(value("new"));
    const hook=renderHook(({ id })=>useReturnRead<ReturnType<typeof value>>(id,load),{ initialProps:{ id:"old" } });
    const signal=load.mock.calls[0][0] as AbortSignal;
    hook.rerender({ id:"new" });
    expect(signal.aborted).toBe(true);
    await waitFor(()=>expect(hook.result.current.data?.id).toBe("new"));
    await act(async()=>finish(value("old")));
    expect(hook.result.current.data?.id).toBe("new");
    hook.unmount();
  });
  it("does not publish a response after authentication changes", async () => {
    let finish!:(v:ReturnType<typeof value>)=>void;
    const hook=renderHook(()=>useReturnRead("scope",()=>new Promise<ReturnType<typeof value>>(resolve=>{finish=resolve;})));
    mock.epoch=2;
    await act(async()=>finish(value("old")));
    expect(hook.result.current.data).toBeNull();
    hook.unmount();
  });
  it("asks the parent to refresh a changed context without retaining the old result", async () => {
    const changed=vi.fn(), load=vi.fn().mockResolvedValueOnce(value("old")).mockRejectedValueOnce(new TradingAssistantApiError({ code:"TA_READ_CONTEXT_CHANGED",message:"changed",fieldErrors:[] } as never));
    const hook=renderHook(()=>useReturnRead("scope",load,changed));
    await waitFor(()=>expect(hook.result.current.data).not.toBeNull());
    act(()=>hook.result.current.refresh());
    await waitFor(()=>expect(changed).toHaveBeenCalledTimes(1));
    expect(hook.result.current.data).toBeNull();
    hook.unmount();
  });
  it("uses the waiting cadence and stops checking a terminal context", async () => {
    vi.useFakeTimers();
    const load=vi.fn().mockResolvedValue(value("same",true));
    mock.status.mockResolvedValue({ stage:"WAITING_DATA",calculationTargetVersion:"1" });
    const hook=renderHook(()=>useReturnRead("scope",load));
    await act(async()=>{});
    await act(async()=>vi.advanceTimersByTimeAsync(2000));
    expect(mock.status).toHaveBeenCalledTimes(1);
    await act(async()=>vi.advanceTimersByTimeAsync(59999));
    expect(mock.status).toHaveBeenCalledTimes(1);
    mock.status.mockResolvedValue({ stage:"PUBLISHED",calculationTargetVersion:"1",publishedGenerationId:"new" });
    await act(async()=>vi.advanceTimersByTimeAsync(1));
    expect(load).toHaveBeenCalledTimes(2);
    await act(async()=>vi.advanceTimersByTimeAsync(60000));
    expect(mock.status).toHaveBeenCalledTimes(2);
    hook.unmount();
  });
  it("does not remount a parent for an unchanged published generation with missing history", async () => {
    vi.useFakeTimers();
    const changed=vi.fn();
    const data=value("same",true);
    data.readContext.accounts[0].publishedGenerationId="published";
    mock.status.mockResolvedValue({ stage:"PUBLISHED",calculationTargetVersion:"1",publishedGenerationId:"published" });
    const hook=renderHook(()=>useReturnRead("scope",async()=>data,changed));
    await act(async()=>{});
    await act(async()=>vi.advanceTimersByTimeAsync(62000));
    expect(mock.status).toHaveBeenCalledTimes(1);
    expect(changed).not.toHaveBeenCalled();
    expect(hook.result.current.data).toBe(data);
    hook.unmount();
  });
  it("aborts when hidden and reads once on return", async () => {
    const visibility=vi.spyOn(document,"visibilityState","get").mockReturnValue("visible");
    const load=vi.fn().mockResolvedValue(value("same"));
    const hook=renderHook(()=>useReturnRead("scope",load));
    await waitFor(()=>expect(hook.result.current.data).not.toBeNull());
    visibility.mockReturnValue("hidden");
    act(()=>document.dispatchEvent(new Event("visibilitychange")));
    expect(load.mock.calls[0][0].aborted).toBe(true);
    visibility.mockReturnValue("visible");
    act(()=>document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(()=>expect(load).toHaveBeenCalledTimes(2));
    hook.unmount();
    act(()=>document.dispatchEvent(new Event("visibilitychange")));
    expect(load).toHaveBeenCalledTimes(2);
  });
});
