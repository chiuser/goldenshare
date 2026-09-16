import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { getRules } from "../api/rulesApi";
import { useRules } from "./useRules";
import type { PlansResponse } from "../api/generatedContracts";
vi.mock("../api/rulesApi", () => ({ getRules: vi.fn() }));
const response = (nextCursor: string | null = null): PlansResponse => ({ items: [], nextCursor, counts: { planCount: 2, alertCount: 1 } });
beforeEach(() => vi.clearAllMocks());
it("does not attach account fields to standalone alerts; pages on the server", async () => {
  vi.mocked(getRules).mockResolvedValueOnce(response("next")).mockResolvedValueOnce(response());
  const { result } = renderHook(() => useRules("ALERT", "irrelevant-account", "ALL", " 测试 ", 0));
  await waitFor(() => expect(result.current.loading).toBe(false));
  expect(getRules).toHaveBeenLastCalledWith("ALERT", { status:"ALL",keyword:"测试",cursor:null },expect.any(AbortSignal));
  act(() => result.current.more());
  await waitFor(() => expect(getRules).toHaveBeenCalledTimes(2));
  expect(getRules).toHaveBeenLastCalledWith("ALERT", { status:"ALL",keyword:"测试",cursor:"next" },expect.any(AbortSignal));
});
it("cancels the old query and discards a late reply after account change", async () => {
  let resolve!: (value: PlansResponse) => void;
  vi.mocked(getRules).mockReturnValueOnce(new Promise(done => { resolve = done; })).mockResolvedValueOnce(response());
  const { result, rerender } = renderHook(({ account }) => useRules("PLAN", account, "ALL", "", 0), { initialProps: { account:"one" } });
  const oldSignal = vi.mocked(getRules).mock.calls[0][2];
  rerender({ account:"two" });
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(async () => resolve({ ...response(), counts: { planCount:99,alertCount:0 } }));
  expect(oldSignal.aborted).toBe(true); expect(result.current.data?.counts.planCount).toBe(2);
});
