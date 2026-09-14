import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { usePositions } from "./usePositions";
import type { PositionsResponse } from "../api/generatedContracts";

const mock = vi.hoisted(() => ({ positions: vi.fn(), status: vi.fn(), epoch: () => 1 }));
vi.mock("../api/positionsApi", () => ({ positionsReadApi: mock }));
const ready = (selected: string) => ({ scope: { accountMode: selected }, coverage: { accounts: [] }, readContext: { accounts: [] } }) as unknown as PositionsResponse;
describe("positions visibility and selection wiring", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible"); mock.positions.mockImplementation(async selected => ready(selected)); });
  afterEach(() => vi.restoreAllMocks());
  it("aborts on hide, refreshes once on visibility and removes listeners on unmount", async () => {
    const hook = renderHook(() => usePositions("one", 0));
    await waitFor(() => expect(hook.result.current.data).not.toBeNull());
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() => expect(mock.positions).toHaveBeenCalledTimes(2));
    hook.unmount();
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    expect(mock.positions).toHaveBeenCalledTimes(2);
  });
  it("does not retain the previous scope while awaiting a new scope or accept its late data", async () => {
    let finish!: (value: PositionsResponse) => void;
    mock.positions.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const hook = renderHook(({ selected }) => usePositions(selected, 0), { initialProps: { selected: "one" } });
    const oldSignal = mock.positions.mock.calls[0][1] as AbortSignal;
    hook.rerender({ selected: "two" });
    expect(oldSignal.aborted).toBe(true);
    await waitFor(() => expect(hook.result.current.data?.scope.accountMode).toBe("two"));
    await act(async () => finish(ready("one")));
    expect(hook.result.current.data?.scope.accountMode).toBe("two");
    act(() => hook.result.current.refresh());
    await waitFor(() => expect(mock.positions).toHaveBeenCalledTimes(3));
    hook.unmount();
  });
});
