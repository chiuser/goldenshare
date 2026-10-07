import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useObserver } from "./useObserver";
import { DataCenterApiError } from "../api/dataCenterApi";
afterEach(() => vi.useRealTimers());
it("a definitive missing or disabled resource waits for manual reread", async () => {
  vi.useFakeTimers(); const read = vi.fn().mockRejectedValue(new DataCenterApiError(404, "DC_DISABLED", "不可用"));
  const { result } = renderHook(() => useObserver(read));
  await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
  expect(read).toHaveBeenCalledTimes(1); expect(result.current.error).toBe("不可用");
  await act(async () => result.current.refresh()); expect(read).toHaveBeenCalledTimes(2);
});
it("sequential polling and cancellation never issue a business stop", async () => {
  vi.useFakeTimers(); let resolve!: (v: number) => void; let signal!: AbortSignal;
  const read = vi.fn((s: AbortSignal) => { signal = s; return new Promise<number>(r => { resolve = r; }); });
  const { unmount } = renderHook(() => useObserver(read, () => true));
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); }); expect(read).toHaveBeenCalledTimes(1);
  await act(async () => { resolve(1); }); await act(async () => { await vi.advanceTimersByTimeAsync(2000); }); expect(read).toHaveBeenCalledTimes(2);
  unmount(); expect(signal.aborted).toBe(true);
});
it("failed observation retains last facts and terminal success stops polling", async () => {
  vi.useFakeTimers(); const read = vi.fn().mockResolvedValueOnce({ phase: "downloading", count: 3 }).mockRejectedValueOnce(new Error("失联")).mockResolvedValue({ phase: "completed", count: 4 });
  const { result } = renderHook(() => useObserver<{ phase: string; count: number }>(read, r => r.phase === "downloading"));
  await act(async () => {}); await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
  expect(result.current.value).toEqual({ phase: "downloading", count: 3 }); expect(result.current.error).toBe("失联");
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); }); expect(result.current.value?.phase).toBe("completed");
  await act(async () => { await vi.advanceTimersByTimeAsync(20000); }); expect(read).toHaveBeenCalledTimes(3);
});
it("refresh retains existing data while read is pending", async () => {
  const read = vi.fn().mockResolvedValueOnce(7).mockImplementationOnce(() => new Promise(() => {}));
  const { result } = renderHook(() => useObserver<number>(read)); await waitFor(() => expect(result.current.value).toBe(7));
  act(() => result.current.refresh()); expect(result.current.value).toBe(7);
});
it("a temporary HTTP 503 still retries and stops once a terminal value is read", async () => {
  vi.useFakeTimers();
  const read = vi.fn().mockRejectedValueOnce(new DataCenterApiError(503, "DC_SOURCE_UNAVAILABLE", "读取暂不可用")).mockResolvedValue({ status: "error" });
  const { result } = renderHook(() => useObserver<{ status: string }>(read, r => r.status === "preparing"));
  await act(async () => {});
  expect(result.current.error).toBe("读取暂不可用");
  await act(async () => { await vi.advanceTimersByTimeAsync(4999); }); expect(read).toHaveBeenCalledTimes(1);
  await act(async () => { await vi.advanceTimersByTimeAsync(1); }); expect(result.current.value?.status).toBe("error");
  await act(async () => { await vi.advanceTimersByTimeAsync(20000); }); expect(read).toHaveBeenCalledTimes(2);
});
