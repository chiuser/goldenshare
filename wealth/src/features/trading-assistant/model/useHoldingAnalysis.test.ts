import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useHoldingAnalysis } from "./useHoldingAnalysis";
import type { PositionsAnalysis } from "../api/generatedContracts";
import { TradingAssistantApiError } from "../api/tradingAssistantApi";

const mocks = vi.hoisted(() => ({ read: vi.fn(), epoch: 1 }));
vi.mock("../api/positionsApi", () => ({ getPositionsAnalysis: mocks.read }));
vi.mock("../../auth/model/authStorage", () => ({ getAuthEpoch: () => mocks.epoch }));
const data = (token: string) => ({ readContext: { contextToken: token } }) as PositionsAnalysis;
describe("analysis is a token-bound child read", () => {
  beforeEach(() => { vi.clearAllMocks(); mocks.epoch = 1; vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible"); mocks.read.mockImplementation(async (_, token) => data(token)); });
  afterEach(() => vi.restoreAllMocks());
  it("aborts old reads and never mixes parent tokens or accounts", async () => {
    let finish!: (value: PositionsAnalysis) => void;
    mocks.read.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const hook = renderHook(({ token }) => useHoldingAnalysis("ALL", token, vi.fn()), { initialProps: { token: "old" } });
    const signal = mocks.read.mock.calls[0][2] as AbortSignal;
    hook.rerender({ token: "new" });
    expect(signal.aborted).toBe(true);
    await waitFor(() => expect(hook.result.current.data?.readContext.contextToken).toBe("new"));
    await act(async () => finish(data("old")));
    expect(hook.result.current.data?.readContext.contextToken).toBe("new");
    hook.unmount();
  });
  it("refreshes the whole parent for changed context, but leaves network errors local", async () => {
    const refresh = vi.fn();
    mocks.read.mockRejectedValueOnce(new TradingAssistantApiError({ code: "TA_READ_CONTEXT_CHANGED" } as never));
    const hook = renderHook(() => useHoldingAnalysis("ALL", "one", refresh));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    mocks.read.mockRejectedValueOnce(new Error("network"));
    act(() => hook.result.current.retry());
    await waitFor(() => expect(hook.result.current.error).toBe(true));
    expect(refresh).toHaveBeenCalledTimes(1);
    hook.unmount();
  });
  it("ignores a response after login changes and stops on hide/unmount", async () => {
    let finish!: (value: PositionsAnalysis) => void;
    mocks.read.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const hook = renderHook(() => useHoldingAnalysis("ALL", "one", vi.fn()));
    mocks.epoch++;
    await act(async () => finish(data("one")));
    expect(hook.result.current.data).toBeNull();
    const signal = mocks.read.mock.calls[0][2] as AbortSignal;
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(signal.aborted).toBe(true);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(hook.result.current.data).not.toBeNull());
    hook.unmount();
  });
});
